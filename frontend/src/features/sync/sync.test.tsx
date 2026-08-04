import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import type { JobCard, SavedSearch, SyncRun } from "../../api/types";
import { App } from "../../app/App";
import { AppProviders } from "../../app/providers";
import { server } from "../../test/server";
import { useSyncRun } from "./useSyncRun";

const origin = "http://localhost:3000";

const SAVED_SEARCH: SavedSearch = {
  id: "search-python",
  name: "Python France",
  keywords: ["python"],
  title: null,
  location: "France",
  radiusKm: null,
  contractTypes: [],
  experienceLevels: [],
  workplaceTypes: [],
  companies: [],
  excludeCompanies: [],
  salaryMin: null,
  sources: ["freework", "linkedin"],
  active: true,
  createdAt: "2026-08-03T08:00:00Z",
  updatedAt: "2026-08-03T09:00:00Z",
};

const JOB: JobCard = {
  id: "job-python",
  title: "Développeur Python",
  company: "Acme",
  location: "Paris",
  salaryMin: null,
  salaryMax: null,
  salaryCurrency: "EUR",
  contractType: "CDI",
  experienceLevel: "Senior",
  remote: true,
  postedAt: "2026-08-03T08:00:00Z",
  sources: [{ source: "Free-Work", url: "https://example.test/free-work", active: true }],
  duplicateState: "none",
  possibleDuplicates: [],
};

const PARTIAL_SYNC: SyncRun = {
  id: "run-partial",
  savedSearchId: SAVED_SEARCH.id,
  status: "partial",
  requestedSources: ["freework", "linkedin"],
  createdAt: "2026-08-04T08:00:00Z",
  startedAt: "2026-08-04T08:00:01Z",
  finishedAt: "2026-08-04T08:00:12Z",
  sources: [
    {
      source: "freework",
      status: "succeeded",
      offersSeen: 12,
      offersPersisted: 4,
      errorMessage: null,
      startedAt: "2026-08-04T08:00:01Z",
      finishedAt: "2026-08-04T08:00:10Z",
    },
    {
      source: "linkedin",
      status: "failed",
      offersSeen: 0,
      offersPersisted: 0,
      errorMessage: "Accès refusé",
      startedAt: "2026-08-04T08:00:01Z",
      finishedAt: "2026-08-04T08:00:12Z",
    },
  ],
};

const RUNNING_SYNC: SyncRun = {
  ...PARTIAL_SYNC,
  id: "run-running",
  status: "running",
  finishedAt: null,
  sources: [
    {
      ...PARTIAL_SYNC.sources[0],
      status: "running",
      finishedAt: null,
    },
  ],
};

function renderAppWithSync(latestSync: SyncRun | null) {
  window.history.replaceState({}, "", "/?search=search-python");
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  server.use(
    http.get(`${origin}/api/searches`, () => HttpResponse.json([SAVED_SEARCH])),
    http.get(`${origin}/api/jobs`, ({ request }) => {
      const url = new URL(request.url);
      return HttpResponse.json({
        items: [JOB],
        total: 1,
        limit: Number(url.searchParams.get("limit")),
        offset: Number(url.searchParams.get("offset")),
      });
    }),
    http.get(`${origin}/api/syncs/latest`, () => HttpResponse.json(latestSync)),
  );
  return {
    user: userEvent.setup(),
    queryClient,
    ...render(
      <AppProviders queryClient={queryClient}>
        <App />
      </AppProviders>,
    ),
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function SyncRunStatus() {
  const syncRun = useSyncRun();
  return <output>{syncRun.run?.status ?? "none"}</output>;
}

describe("synchronisation manuelle", () => {
  it("reste utilisable et relance uniquement la source en échec", async () => {
    const retries: Array<{ runId: string; source: string }> = [];
    server.use(
      http.post(`${origin}/api/syncs/:runId/retry`, async ({ params, request }) => {
        retries.push({
          runId: String(params.runId),
          source: String((await request.json() as { source: string }).source),
        });
        return HttpResponse.json(RUNNING_SYNC, { status: 202 });
      }),
    );
    const { user } = renderAppWithSync(PARTIAL_SYNC);

    expect(await screen.findByText("Free-Work : terminée")).toBeVisible();
    expect(screen.getByText("LinkedIn : échec")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Relancer LinkedIn" }));

    await waitFor(() =>
      expect(retries).toEqual([{ runId: PARTIAL_SYNC.id, source: "linkedin" }]),
    );
    expect(screen.getByText("Développeur Python")).toBeVisible();
  });

  it("démarre la recherche sélectionnée sans bloquer les résultats", async () => {
    let resolveStart: ((run: SyncRun) => void) | undefined;
    const start = new Promise<SyncRun>((resolve) => {
      resolveStart = resolve;
    });
    const starts: string[] = [];
    server.use(
      http.post(`${origin}/api/syncs`, async ({ request }) => {
        starts.push(String((await request.json() as { savedSearchId: string }).savedSearchId));
        return HttpResponse.json(await start, { status: 202 });
      }),
    );
    const { user } = renderAppWithSync(null);

    await screen.findByRole("combobox", { name: "Recherche enregistrée" });
    const refresh = screen.getByRole("button", { name: "Actualiser" });
    await waitFor(() => expect(refresh).toBeEnabled());
    await user.click(refresh);

    expect(refresh).toBeDisabled();
    expect(screen.getByText("Développeur Python")).toBeVisible();
    resolveStart?.(RUNNING_SYNC);
    await waitFor(() => expect(starts).toEqual([SAVED_SEARCH.id]));
    expect(await screen.findByText("Free-Work : en cours")).toBeVisible();
    expect(refresh).toBeDisabled();
  });

  it("poll toutes les cinq secondes pendant une synchronisation active puis s’arrête", async () => {
    vi.useFakeTimers();
    let resolveTerminal!: (run: SyncRun) => void;
    const terminalResponse = new Promise<SyncRun>((resolve) => {
      resolveTerminal = resolve;
    });
    const getLatestSync = vi
      .spyOn(api, "getLatestSync")
      .mockResolvedValueOnce(RUNNING_SYNC)
      .mockReturnValueOnce(terminalResponse);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    const rendered = render(
      <QueryClientProvider client={queryClient}>
        <SyncRunStatus />
      </QueryClientProvider>,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("status")).toHaveTextContent("running");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(getLatestSync).toHaveBeenCalledTimes(2);
    await act(async () => {
      resolveTerminal(PARTIAL_SYNC);
      await terminalResponse;
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("status")).toHaveTextContent("partial");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(getLatestSync).toHaveBeenCalledTimes(2);
    rendered.unmount();
  });
});
