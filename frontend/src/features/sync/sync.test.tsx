import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
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
  maxResults: 500,
  sources: ["freework", "linkedin"],
  active: true,
  createdAt: "2026-08-03T08:00:00Z",
  updatedAt: "2026-08-03T09:00:00Z",
};

const OTHER_SAVED_SEARCH: SavedSearch = {
  ...SAVED_SEARCH,
  id: "search-data",
  name: "Data France",
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

const PRODUCTIVE_PARTIAL_SYNC: SyncRun = {
  ...PARTIAL_SYNC,
  sources: [
    {
      ...PARTIAL_SYNC.sources[0],
      status: "partial",
      errorMessage: "Une partie des offres seulement a été récupérée.",
    },
    PARTIAL_SYNC.sources[1],
  ],
};

const FAILED_SYNC: SyncRun = {
  ...PARTIAL_SYNC,
  id: "run-failed",
  status: "failed",
  sources: [
    {
      ...PARTIAL_SYNC.sources[0],
      status: "failed",
      offersSeen: 0,
      offersPersisted: 0,
      errorMessage: "Échec temporaire",
    },
  ],
};

const RETRIED_PARTIAL_SYNC: SyncRun = {
  ...PRODUCTIVE_PARTIAL_SYNC,
  id: "run-retried-partial",
  requestedSources: ["freework"],
  sources: [PRODUCTIVE_PARTIAL_SYNC.sources[0]],
};

function renderAppWithSync(
  latestSync: SyncRun | null,
  options: {
    initialUrl?: string;
    searches?: SavedSearch[];
    latestSyncBySearch?: Record<string, SyncRun | null>;
  } = {},
) {
  window.history.replaceState({}, "", options.initialUrl ?? "/?search=search-python");
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  server.use(
    http.get(`${origin}/api/searches`, () =>
      HttpResponse.json(options.searches ?? [SAVED_SEARCH]),
    ),
    http.get(`${origin}/api/jobs`, ({ request }) => {
      const url = new URL(request.url);
      return HttpResponse.json({
        items: [JOB],
        total: 1,
        limit: Number(url.searchParams.get("limit")),
        offset: Number(url.searchParams.get("offset")),
      });
    }),
    http.get(`${origin}/api/syncs/latest`, ({ request }) => {
      const searchId = new URL(request.url).searchParams.get("savedSearchId");
      return HttpResponse.json(
        searchId === null
          ? latestSync
          : (options.latestSyncBySearch?.[searchId] ?? latestSync),
      );
    }),
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

function SyncRunStatus({ savedSearchId = SAVED_SEARCH.id }: { savedSearchId?: string }) {
  const syncRun = useSyncRun(savedSearchId);
  return <output>{syncRun.run?.status ?? "none"}</output>;
}

function JobQueryObserver({ onFetch }: { onFetch: () => void }) {
  useQuery({
    queryKey: ["jobs", "existing"],
    queryFn: () => {
      onFetch();
      return { items: [], total: 0, limit: 24, offset: 0 };
    },
    staleTime: Infinity,
  });
  return null;
}

function JobDetailsQueryObserver({ onFetch }: { onFetch: () => void }) {
  useQuery({
    queryKey: ["job-details", JOB.id],
    queryFn: () => {
      onFetch();
      return null;
    },
    staleTime: Infinity,
  });
  return null;
}

function RetrySourceControl() {
  const syncRun = useSyncRun(SAVED_SEARCH.id);
  if (syncRun.run === null) {
    return null;
  }
  return (
    <button
      type="button"
      onClick={() => void syncRun.retrySource(syncRun.run!.id, "freework")}
    >
      Relancer le test
    </button>
  );
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

  it("permet de relancer une source partielle en conservant son erreur", async () => {
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
    const { user } = renderAppWithSync(PRODUCTIVE_PARTIAL_SYNC);

    expect(
      await screen.findByText("Une partie des offres seulement a été récupérée."),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Relancer Free-Work" }));

    await waitFor(() =>
      expect(retries).toEqual([
        { runId: PRODUCTIVE_PARTIAL_SYNC.id, source: "freework" },
      ]),
    );
  });

  it("affiche les compteurs et l’heure française seulement lorsqu’ils existent", async () => {
    renderAppWithSync(PRODUCTIVE_PARTIAL_SYNC);

    const partial = (await screen.findByText("Free-Work : partielle")).closest("li");
    expect(partial).not.toBeNull();
    expect(
      within(partial as HTMLElement).getByText(
        "12 offres vues · 4 offres enregistrées",
      ),
    ).toBeVisible();
    expect(
      within(partial as HTMLElement).getByText(
        "Terminée le 4 août 2026 à 10:00",
      ),
    ).toBeVisible();

    const failed = screen.getByText("LinkedIn : échec").closest("li");
    expect(failed).not.toBeNull();
    expect(
      within(failed as HTMLElement).getByText(
        "0 offres vues · 0 offres enregistrées",
      ),
    ).toBeVisible();
    expect(
      within(partial as HTMLElement).queryByText(/information indisponible/i),
    ).toBeNull();
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

  it("verrouille seulement la recherche en cours de lancement", async () => {
    let resolveStart!: (run: SyncRun) => void;
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
    const { user } = renderAppWithSync(null, {
      searches: [SAVED_SEARCH, OTHER_SAVED_SEARCH],
    });

    const selector = await screen.findByRole("combobox", {
      name: "Recherche enregistrée",
    });
    const refresh = screen.getByRole("button", { name: "Actualiser" });
    await user.click(refresh);
    await waitFor(() => expect(starts).toEqual([SAVED_SEARCH.id]));
    expect(refresh).toBeDisabled();

    await user.selectOptions(selector, OTHER_SAVED_SEARCH.id);
    await waitFor(() => expect(refresh).toBeEnabled());

    await user.selectOptions(selector, SAVED_SEARCH.id);
    expect(refresh).toBeDisabled();

    resolveStart({ ...RUNNING_SYNC, savedSearchId: SAVED_SEARCH.id });
    await screen.findByText("Free-Work : en cours");
  });

  it("verrouille seulement la recherche déjà synchronisée", async () => {
    const starts: string[] = [];
    server.use(
      http.post(`${origin}/api/syncs`, async ({ request }) => {
        starts.push(String((await request.json() as { savedSearchId: string }).savedSearchId));
        return HttpResponse.json(RUNNING_SYNC, { status: 202 });
      }),
    );
    const runningOtherSearch: SyncRun = {
      ...RUNNING_SYNC,
      savedSearchId: SAVED_SEARCH.id,
    };
    const first = renderAppWithSync(runningOtherSearch, {
      initialUrl: `/?search=${OTHER_SAVED_SEARCH.id}`,
      searches: [SAVED_SEARCH, OTHER_SAVED_SEARCH],
    });

    const refreshForOtherSearch = await screen.findByRole("button", {
      name: "Actualiser",
    });
    await waitFor(() => expect(refreshForOtherSearch).toBeEnabled());
    await first.user.click(refreshForOtherSearch);
    await waitFor(() => expect(starts).toEqual([OTHER_SAVED_SEARCH.id]));
    first.unmount();

    renderAppWithSync(runningOtherSearch);
    expect(await screen.findByRole("button", { name: "Actualiser" })).toBeDisabled();
  });

  it("conserve séparément les synchronisations actives lors des changements A/B", async () => {
    const runningA: SyncRun = {
      ...RUNNING_SYNC,
      savedSearchId: SAVED_SEARCH.id,
    };
    const terminalB: SyncRun = {
      ...PARTIAL_SYNC,
      id: "run-data-newer",
      savedSearchId: OTHER_SAVED_SEARCH.id,
      createdAt: "2026-08-04T09:00:00Z",
    };
    const { user, queryClient } = renderAppWithSync(null, {
      searches: [SAVED_SEARCH, OTHER_SAVED_SEARCH],
      latestSyncBySearch: {
        [SAVED_SEARCH.id]: runningA,
        [OTHER_SAVED_SEARCH.id]: terminalB,
      },
    });

    const selector = await screen.findByRole("combobox", {
      name: "Recherche enregistrée",
    });
    const refresh = screen.getByRole("button", { name: "Actualiser" });
    await waitFor(() => expect(refresh).toBeDisabled());

    await user.selectOptions(selector, OTHER_SAVED_SEARCH.id);
    await waitFor(() => expect(refresh).toBeEnabled());
    expect(queryClient.getQueryData(["sync", "latest", OTHER_SAVED_SEARCH.id])).toEqual(
      terminalB,
    );

    await user.selectOptions(selector, SAVED_SEARCH.id);
    await waitFor(() => expect(refresh).toBeDisabled());
    expect(queryClient.getQueryData(["sync", "latest", SAVED_SEARCH.id])).toEqual(
      runningA,
    );
  });

  it("invalide offres et détails une fois par version de progrès productrice", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    queryClient.setQueryData(["jobs", "existing"], {
      items: [],
      total: 0,
      limit: 24,
      offset: 0,
    });
    queryClient.setQueryData(["job-details", JOB.id], null);
    const getLatestSync = vi
      .spyOn(api, "getLatestSync")
      .mockResolvedValue(PRODUCTIVE_PARTIAL_SYNC);
    let jobFetches = 0;
    let detailFetches = 0;
    const rendered = render(
      <QueryClientProvider client={queryClient}>
        <SyncRunStatus />
        <JobQueryObserver onFetch={() => { jobFetches += 1; }} />
        <JobDetailsQueryObserver onFetch={() => { detailFetches += 1; }} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("partial");
    });
    await waitFor(() => expect(jobFetches).toBe(1));
    await waitFor(() => expect(detailFetches).toBe(1));
    rendered.rerender(
      <QueryClientProvider client={queryClient}>
        <SyncRunStatus />
        <JobQueryObserver onFetch={() => { jobFetches += 1; }} />
        <JobDetailsQueryObserver onFetch={() => { detailFetches += 1; }} />
      </QueryClientProvider>,
    );
    queryClient.setQueryData(["sync", "latest", SAVED_SEARCH.id], {
      ...PRODUCTIVE_PARTIAL_SYNC,
    });
    await waitFor(() => expect(getLatestSync).toHaveBeenCalledTimes(1));
    expect(jobFetches).toBe(1);
    expect(detailFetches).toBe(1);

    queryClient.setQueryData(["sync", "latest", SAVED_SEARCH.id], {
      ...PRODUCTIVE_PARTIAL_SYNC,
      sources: PRODUCTIVE_PARTIAL_SYNC.sources.map((source) =>
        source.source === "freework"
          ? {
              ...source,
              offersPersisted: 5,
              finishedAt: "2026-08-04T08:00:15Z",
            }
          : source,
      ),
    });
    await waitFor(() => expect(jobFetches).toBe(2));
    await waitFor(() => expect(detailFetches).toBe(2));

    queryClient.setQueryData(["sync", "latest", SAVED_SEARCH.id], {
      ...PRODUCTIVE_PARTIAL_SYNC,
      id: "run-partial-empty",
      sources: [
        {
          ...PRODUCTIVE_PARTIAL_SYNC.sources[0],
          offersPersisted: 0,
        },
      ],
    });
    await waitFor(() => expect(getLatestSync).toHaveBeenCalledTimes(1));
    expect(jobFetches).toBe(2);
    expect(detailFetches).toBe(2);
    rendered.unmount();
  });

  it("invalide offres et détails quand un retry devient partiellement producteur", async () => {
    vi.spyOn(api, "getLatestSync").mockResolvedValue(FAILED_SYNC);
    server.use(
      http.post(`${origin}/api/syncs/:runId/retry`, () =>
        HttpResponse.json(RETRIED_PARTIAL_SYNC, { status: 202 }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    queryClient.setQueryData(["jobs", "existing"], {
      items: [],
      total: 0,
      limit: 24,
      offset: 0,
    });
    queryClient.setQueryData(["job-details", JOB.id], null);
    let jobFetches = 0;
    let detailFetches = 0;
    const user = userEvent.setup();
    const rendered = render(
      <QueryClientProvider client={queryClient}>
        <RetrySourceControl />
        <JobQueryObserver onFetch={() => { jobFetches += 1; }} />
        <JobDetailsQueryObserver onFetch={() => { detailFetches += 1; }} />
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "Relancer le test" }));

    await waitFor(() => expect(jobFetches).toBe(1));
    await waitFor(() => expect(detailFetches).toBe(1));
    expect(
      queryClient.getQueryData(["sync", "latest", SAVED_SEARCH.id]),
    ).toEqual(RETRIED_PARTIAL_SYNC);
    rendered.unmount();
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
    queryClient.setQueryData(["jobs", "existing"], {
      items: [],
      total: 0,
      limit: 24,
      offset: 0,
    });
    queryClient.setQueryData(["job-details", JOB.id], null);
    let jobFetches = 0;
    let detailFetches = 0;
    const rendered = render(
      <QueryClientProvider client={queryClient}>
        <SyncRunStatus />
        <JobQueryObserver onFetch={() => { jobFetches += 1; }} />
        <JobDetailsQueryObserver onFetch={() => { detailFetches += 1; }} />
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
    expect(jobFetches).toBe(1);
    expect(detailFetches).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(getLatestSync).toHaveBeenCalledTimes(2);
    rendered.unmount();
  });
});
