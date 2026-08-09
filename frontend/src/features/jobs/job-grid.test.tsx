import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type {
  JobCard,
  JobFilters,
  JobsPage,
  SavedSearch,
} from "../../api/types";
import { App } from "../../app/App";
import { AppProviders } from "../../app/providers";
import { server } from "../../test/server";

const origin = "http://localhost:3000";

const savedSearch: SavedSearch = {
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

const POSSIBLE_DUPLICATE_JOB: JobCard = {
  id: "job-python",
  title: "Développeur Python",
  company: "Acme",
  location: "Paris",
  salaryMin: 52_000,
  salaryMax: 64_000,
  salaryCurrency: "EUR",
  contractType: "CDI",
  experienceLevel: "Senior",
  remote: true,
  postedAt: "2026-08-03T08:00:00Z",
  viewedAt: null,
  sources: [
    { source: "Free-Work", url: "https://example.test/free-work", active: true },
    { source: "LinkedIn", url: "https://example.test/linkedin", active: true },
  ],
  duplicateState: "possible",
  possibleDuplicates: [
    {
      id: "job-python-copy",
      title: "Python Developer",
      company: "Acme",
      location: "Paris",
      score: 0.92,
      reasons: ["Titre similaire"],
    },
  ],
};

function renderAppWithJobs(
  jobs: JobCard[],
  options: {
    initialUrl?: string;
    total?: number;
    queryClient?: QueryClient;
    getJobs?: (url: URL) => { items: JobCard[]; total: number };
  } = {},
) {
  window.history.replaceState({}, "", options.initialUrl ?? "/?search=search-python");
  server.use(
    http.get(`${origin}/api/searches`, () => HttpResponse.json([savedSearch])),
    http.get(`${origin}/api/jobs`, ({ request }) => {
      const url = new URL(request.url);
      const response = options.getJobs?.(url) ?? {
        items: jobs,
        total: options.total ?? jobs.length,
      };
      return HttpResponse.json({
        ...response,
        limit: Number(url.searchParams.get("limit")),
        offset: Number(url.searchParams.get("offset")),
      });
    }),
    http.get(`${origin}/api/jobs/:id`, ({ params }) =>
      HttpResponse.json({
        ...(jobs[0] ?? POSSIBLE_DUPLICATE_JOB),
        id: String(params.id),
        description: null,
        skills: [],
        benefits: [],
        cacheState: "fresh",
        updatedAt: "2026-08-09T10:00:00Z",
        warning: null,
      }),
    ),
  );
  return renderApplication(options.queryClient);
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
}

function renderApplication(queryClient = createQueryClient()) {
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

describe("grille des offres", () => {
  beforeEach(() => {
    server.use(
      http.post("*/api/jobs/:id/viewed", ({ params }) =>
        HttpResponse.json({
          id: String(params.id),
          viewedAt: "2026-08-09T10:00:00Z",
        }),
      ),
    );
  });

  it("affiche les sources et le doublon possible", async () => {
    renderAppWithJobs([POSSIBLE_DUPLICATE_JOB]);

    expect(await screen.findByText("Développeur Python")).toBeVisible();
    const card = screen.getByRole("button", { name: "Voir l’offre Développeur Python" });
    expect(within(card).getByText("Free-Work")).toBeVisible();
    expect(within(card).getByText("LinkedIn")).toBeVisible();
    expect(within(card).getByText("Doublon possible")).toBeVisible();
  });

  it("attenuates a viewed card and exposes the explicit label", async () => {
    server.use(
      http.get("*/api/jobs", () =>
        HttpResponse.json({
          items: [
            {
              ...POSSIBLE_DUPLICATE_JOB,
              viewedAt: "2026-08-09T10:00:00Z",
            },
          ],
          total: 1,
          limit: 24,
          offset: 0,
        }),
      ),
    );

    renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: "2026-08-09T10:00:00Z" }]);

    const card = await screen.findByRole("article");
    expect(card).toHaveClass("job-card--viewed");
    expect(within(card).getByText("✓ Déjà vue")).toBeVisible();
  });

  it("does not change the presentation of an unseen card", async () => {
    renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }]);

    const card = await screen.findByRole("article");
    expect(card).not.toHaveClass("job-card--viewed");
    expect(within(card).queryByText("✓ Déjà vue")).not.toBeInTheDocument();
  });

  it("traduit les slugs API sur les cartes", async () => {
    renderAppWithJobs([
      {
        ...POSSIBLE_DUPLICATE_JOB,
        contractType: "cdi",
        sources: [
          {
            source: "freework",
            url: "https://example.test/free-work",
            active: true,
          },
        ],
      },
    ]);

    const card = await screen.findByRole("button", {
      name: "Voir l’offre Développeur Python",
    });
    expect(within(card).getByText("Free-Work")).toBeVisible();
    expect(card).toHaveTextContent("CDI");
    expect(card).not.toHaveTextContent("freework");
    expect(card).not.toHaveTextContent("cdi");
  });

  it("affiche un état vide lorsque l’API ne retourne aucune offre", async () => {
    renderAppWithJobs([]);

    expect(
      await screen.findByText("Aucune offre ne correspond à ces filtres"),
    ).toBeVisible();
  });

  it("relance le chargement des offres après une erreur API", async () => {
    let attempts = 0;
    window.history.replaceState({}, "", "/?search=search-python");
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json([savedSearch])),
      http.get(`${origin}/api/jobs`, () => {
        attempts += 1;
        if (attempts === 1) {
          return HttpResponse.json({ message: "Erreur" }, { status: 500 });
        }
        return HttpResponse.json({ items: [], total: 0, limit: 24, offset: 0 });
      }),
    );
    const { user } = renderApplication();

    await user.click(await screen.findByRole("button", { name: "Réessayer" }));

    expect(
      await screen.findByText("Aucune offre ne correspond à ces filtres"),
    ).toBeVisible();
    expect(attempts).toBe(2);
  });

  it("charge la page suivante avec un offset de 24", async () => {
    const secondPageJob = { ...POSSIBLE_DUPLICATE_JOB, id: "job-page-2", title: "Data engineer" };
    const offsets: string[] = [];
    window.history.replaceState({}, "", "/?search=search-python");
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json([savedSearch])),
      http.get(`${origin}/api/jobs`, ({ request }) => {
        const offset = new URL(request.url).searchParams.get("offset") ?? "";
        offsets.push(offset);
        return HttpResponse.json({
          items: offset === "24" ? [secondPageJob] : [POSSIBLE_DUPLICATE_JOB],
          total: 25,
          limit: 24,
          offset: Number(offset),
        });
      }),
    );
    const { user } = renderApplication();

    await screen.findByText("Développeur Python");
    await user.click(screen.getByRole("button", { name: "Page suivante" }));

    expect(await screen.findByText("Data engineer")).toBeVisible();
    expect(offsets).toEqual(["0", "24"]);
  });

  it("sélectionne une offre dans l’URL sans perdre les filtres", async () => {
    const { user } = renderAppWithJobs([POSSIBLE_DUPLICATE_JOB], {
      initialUrl: "/?search=search-python&period=7d&source=freework",
    });

    await user.click(
      await screen.findByRole("button", { name: "Voir l’offre Développeur Python" }),
    );

    const params = new URLSearchParams(window.location.search);
    expect(params.get("job")).toBe("job-python");
    expect(params.get("search")).toBe("search-python");
    expect(params.get("period")).toBe("7d");
    expect(params.get("source")).toBe("freework");
  });

  it("opens details immediately and posts viewed state from a grid card", async () => {
    const user = userEvent.setup();
    let markRequests = 0;
    let serverViewedAt: string | null = null;
    server.use(
      http.post("*/api/jobs/:id/viewed", ({ params }) => {
        markRequests += 1;
        serverViewedAt = "2026-08-09T10:00:00Z";
        return HttpResponse.json({
          id: String(params.id),
          viewedAt: serverViewedAt,
        });
      }),
    );

    renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }], {
      getJobs: () => ({
        items: [{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: serverViewedAt }],
        total: 1,
      }),
    });
    await user.click(
      await screen.findByRole("button", {
        name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}`,
      }),
    );

    expect(window.location.search).toContain(`job=${POSSIBLE_DUPLICATE_JOB.id}`);
    await waitFor(() => expect(markRequests).toBe(1));
    expect(await screen.findByText("✓ Déjà vue")).toBeVisible();
  });

  it("removes the card and decrements total immediately with unseen-only enabled", async () => {
    const user = userEvent.setup();
    let releaseRequest: (() => void) | undefined;
    server.use(
      http.post("*/api/jobs/:id/viewed", async ({ params }) => {
        await new Promise<void>((resolve) => {
          releaseRequest = resolve;
        });
        return HttpResponse.json({
          id: String(params.id),
          viewedAt: "2026-08-09T10:00:00Z",
        });
      }),
    );

    renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }], {
      initialUrl: "/?period=3d&unseenOnly=true",
    });
    await screen.findByRole("button", {
      name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}`,
    });
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get("search")).toBe(
        "search-python",
      ),
    );
    await user.click(
      await screen.findByRole("button", {
        name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}`,
      }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}`,
        }),
      ).not.toBeInTheDocument(),
    );
    expect(window.location.search).toContain(`job=${POSSIBLE_DUPLICATE_JOB.id}`);
    releaseRequest?.();
  });

  it("restores every cached page and reports an accessible error when marking fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("*/api/jobs/:id/viewed", () =>
        HttpResponse.json({ detail: "database unavailable" }, { status: 500 }),
      ),
    );

    renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }], {
      initialUrl: "/?period=3d&unseenOnly=true",
    });
    await screen.findByRole("button", {
      name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}`,
    });
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get("search")).toBe(
        "search-python",
      ),
    );
    await user.click(
      await screen.findByRole("button", {
        name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}`,
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Impossible d’enregistrer cette offre comme déjà vue.",
    );
    expect(
      await screen.findByRole("button", {
        name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}`,
      }),
    ).toBeVisible();
    expect(window.location.search).toContain(`job=${POSSIBLE_DUPLICATE_JOB.id}`);
  });

  it("reconciles every cached jobs page after an optimistic mark", async () => {
    const user = userEvent.setup();
    let releaseRequest: (() => void) | undefined;
    let serverViewedAt: string | null = null;
    let jobsRequests = 0;
    server.use(
      http.post("*/api/jobs/:id/viewed", async ({ params }) => {
        await new Promise<void>((resolve) => {
          releaseRequest = () => {
            serverViewedAt = "2026-08-09T10:00:00Z";
            resolve();
          };
        });
        return HttpResponse.json({
          id: String(params.id),
          viewedAt: serverViewedAt,
        });
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: Infinity },
        mutations: { retry: false },
      },
    });
    const normalFilters: JobFilters = {
      savedSearchId: "search-python",
      period: "3d",
      sort: "date",
      limit: 24,
      offset: 0,
    };
    const unseenFilters: JobFilters = { ...normalFilters, unseenOnly: true };
    const page: JobsPage = {
      items: [{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }],
      total: 1,
      limit: 24,
      offset: 0,
    };
    queryClient.setQueryData(["jobs", normalFilters], page);
    queryClient.setQueryData(["jobs", unseenFilters], page);

    renderAppWithJobs([{ ...POSSIBLE_DUPLICATE_JOB, viewedAt: null }], {
      initialUrl: "/?search=search-python&period=3d&unseenOnly=true",
      queryClient,
      getJobs: (url) => {
        jobsRequests += 1;
        const job = { ...POSSIBLE_DUPLICATE_JOB, viewedAt: serverViewedAt };
        const hidesViewed =
          url.searchParams.get("unseenOnly") === "true" && serverViewedAt !== null;
        return { items: hidesViewed ? [] : [job], total: hidesViewed ? 0 : 1 };
      },
    });
    await waitFor(() => expect(jobsRequests).toBeGreaterThan(0));
    await user.click(
      await screen.findByRole("button", {
        name: `Voir l’offre ${POSSIBLE_DUPLICATE_JOB.title}`,
      }),
    );

    await waitFor(() => {
      expect(
        queryClient.getQueryData<JobsPage>(["jobs", normalFilters])?.items[0]
          ?.viewedAt,
      ).not.toBeNull();
    });
    expect(queryClient.getQueryData<JobsPage>(["jobs", unseenFilters])).toMatchObject({
      items: [],
      total: 0,
    });

    const requestsBeforeRelease = jobsRequests;
    releaseRequest?.();

    await waitFor(() =>
      expect(
        queryClient.getQueryData<JobsPage>(["jobs", normalFilters])?.items[0],
      ).toMatchObject({
        id: POSSIBLE_DUPLICATE_JOB.id,
        viewedAt: "2026-08-09T10:00:00Z",
      }),
    );
    await waitFor(() => expect(jobsRequests).toBeGreaterThan(requestsBeforeRelease));
    expect(queryClient.getQueryData<JobsPage>(["jobs", unseenFilters])).toMatchObject({
      items: [],
      total: 0,
    });
  });

  it("n’invente pas les informations absentes d’une offre", async () => {
    renderAppWithJobs([
      {
        ...POSSIBLE_DUPLICATE_JOB,
        id: "job-minimal",
        title: "Offre sans détails",
        company: "",
        location: "",
        salaryMin: null,
        salaryMax: null,
        salaryCurrency: "",
        contractType: null,
        remote: null,
        postedAt: null,
        sources: [],
        duplicateState: "none",
      },
    ]);

    const card = await screen.findByRole("button", { name: "Voir l’offre Offre sans détails" });
    expect(card).not.toHaveTextContent("Télétravail");
    expect(card).not.toHaveTextContent("Sur site");
    expect(card).not.toHaveTextContent("À partir de");
  });
});
