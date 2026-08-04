import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { JobCard, JobDetails, SavedSearch } from "../../api/types";
import { App } from "../../app/App";
import { AppProviders } from "../../app/providers";
import { server } from "../../test/server";

const origin = "http://localhost:3000";
const POSSIBLE_DUPLICATE_ID = "job-backend-python";

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
  sources: ["freework"],
  active: true,
  createdAt: "2026-08-03T08:00:00Z",
  updatedAt: "2026-08-03T09:00:00Z",
};

const JOB: JobCard = {
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
  sources: [
    { source: "Free-Work", url: "https://example.test/free-work", active: true },
  ],
  duplicateState: "possible",
  possibleDuplicates: [
    {
      id: POSSIBLE_DUPLICATE_ID,
      title: "Backend Python",
      company: "Acme",
      location: "Paris",
      score: 0.92,
      reasons: ["Titre similaire"],
    },
  ],
};

const DETAILS_WITH_DUPLICATE: JobDetails = {
  ...JOB,
  description: "Une première mission.\n\nUne seconde mission.",
  skills: ["Python", "FastAPI"],
  benefits: ["Télétravail"],
  cacheState: "fresh",
  updatedAt: "2026-08-04T08:00:00Z",
  warning: null,
};

function renderAppWithJobs(
  jobs: JobCard[],
  options: {
    details: JobDetails;
    initialUrl?: string;
    loadDetails?: () => Promise<JobDetails>;
    detailsStatus?: () => number;
    onDetailsRequest?: (id: string) => void;
  },
) {
  window.history.replaceState(
    {},
    "",
    options.initialUrl ?? "/?search=search-python&period=7d",
  );
  server.use(
    http.get(`${origin}/api/searches`, () => HttpResponse.json([SAVED_SEARCH])),
    http.get(`${origin}/api/jobs`, ({ request }) => {
      const url = new URL(request.url);
      return HttpResponse.json({
        items: jobs,
        total: jobs.length,
        limit: Number(url.searchParams.get("limit")),
        offset: Number(url.searchParams.get("offset")),
      });
    }),
    http.get(`${origin}/api/jobs/:id`, async ({ params }) => {
      options.onDetailsRequest?.(String(params.id));
      const status = options.detailsStatus?.() ?? 200;
      if (status !== 200) {
        return HttpResponse.json({ detail: "Erreur de détail" }, { status });
      }
      const details = options.loadDetails
        ? await options.loadDetails()
        : options.details;
      return HttpResponse.json({ ...details, id: String(params.id) });
    }),
  );
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return {
    user: userEvent.setup(),
    ...render(
      <AppProviders queryClient={queryClient}>
        <App />
      </AppProviders>,
    ),
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("détails d’une offre", () => {
  it("ouvre les détails et suit un doublon possible", async () => {
    vi.setSystemTime(new Date("2026-08-04T12:00:00Z"));
    const detailIds: string[] = [];
    const { user } = renderAppWithJobs([JOB], {
      details: DETAILS_WITH_DUPLICATE,
      onDetailsRequest: (id) => detailIds.push(id),
    });

    await user.click(
      await screen.findByRole("button", { name: "Voir l’offre Développeur Python" }),
    );

    expect(
      await screen.findByRole("dialog", { name: "Détails de l’offre" }),
    ).toBeVisible();
    expect(screen.getByText("Détails mis à jour aujourd’hui")).toBeVisible();
    await user.click(
      screen.getByRole("button", {
        name: "Voir l’offre similaire Backend Python",
      }),
    );
    const params = new URLSearchParams(window.location.search);
    expect(params.get("job")).toBe(POSSIBLE_DUPLICATE_ID);
    expect(params.get("search")).toBe("search-python");
    expect(params.get("period")).toBe("7d");
    await waitFor(() => {
      expect(detailIds).toEqual(["job-python", POSSIBLE_DUPLICATE_ID]);
    });
  });

  it("ferme le drawer sans perdre les filtres et restaure le focus", async () => {
    const { user } = renderAppWithJobs([JOB], {
      details: DETAILS_WITH_DUPLICATE,
      initialUrl:
        "/?search=search-python&period=7d&source=freework&source=linkedin",
    });
    const trigger = await screen.findByRole("button", {
      name: "Voir l’offre Développeur Python",
    });
    await user.click(trigger);
    await screen.findByRole("dialog", { name: "Détails de l’offre" });

    await user.click(screen.getByRole("button", { name: "Fermer les détails" }));

    expect(screen.queryByRole("dialog", { name: "Détails de l’offre" })).toBeNull();
    const params = new URLSearchParams(window.location.search);
    expect(params.has("job")).toBe(false);
    expect(params.get("search")).toBe("search-python");
    expect(params.get("period")).toBe("7d");
    expect(params.getAll("source")).toEqual(["freework", "linkedin"]);
    expect(trigger).toHaveFocus();
  });

  it("piège le focus dans le drawer et se ferme avec Échap", async () => {
    const { user } = renderAppWithJobs([JOB], {
      details: DETAILS_WITH_DUPLICATE,
    });
    await user.click(
      await screen.findByRole("button", { name: "Voir l’offre Développeur Python" }),
    );
    await screen.findByRole("button", {
      name: "Voir l’offre similaire Backend Python",
    });
    const closeButton = screen.getByRole("button", { name: "Fermer les détails" });
    const duplicateButton = screen.getByRole("button", {
      name: "Voir l’offre similaire Backend Python",
    });

    expect(closeButton).toHaveFocus();
    await user.tab({ shift: true });
    expect(duplicateButton).toHaveFocus();
    await user.tab();
    expect(closeButton).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Détails de l’offre" })).toBeNull();
  });

  it("affiche le chargement lors de l’ouverture par lien direct", async () => {
    let resolveDetails!: (details: JobDetails) => void;
    const pendingDetails = new Promise<JobDetails>((resolve) => {
      resolveDetails = resolve;
    });
    renderAppWithJobs([JOB], {
      details: DETAILS_WITH_DUPLICATE,
      initialUrl: "/?search=search-python&period=7d&job=job-python",
      loadDetails: () => pendingDetails,
    });

    expect(
      await screen.findByRole("dialog", { name: "Détails de l’offre" }),
    ).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Chargement des détails…");

    resolveDetails(DETAILS_WITH_DUPLICATE);
    expect(
      await within(
        screen.getByRole("dialog", { name: "Détails de l’offre" }),
      ).findByText("Développeur Python"),
    ).toBeVisible();
  });

  it("réessaie le chargement des détails après une erreur", async () => {
    let attempts = 0;
    const { user } = renderAppWithJobs([JOB], {
      details: DETAILS_WITH_DUPLICATE,
      initialUrl: "/?search=search-python&job=job-python",
      detailsStatus: () => {
        attempts += 1;
        return attempts === 1 ? 500 : 200;
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Impossible de charger les détails.",
    );
    await user.click(screen.getByRole("button", { name: "Réessayer" }));

    expect(
      await within(
        screen.getByRole("dialog", { name: "Détails de l’offre" }),
      ).findByText("Développeur Python"),
    ).toBeVisible();
    expect(attempts).toBe(2);
  });

  it("rend la description non fiable comme texte en préservant sa structure", async () => {
    const unsafeDescription =
      '<img src="x" onerror="alert(1)"> Première ligne\nSeconde ligne\n\nSecond paragraphe';
    renderAppWithJobs([JOB], {
      details: {
        ...DETAILS_WITH_DUPLICATE,
        description: unsafeDescription,
      },
      initialUrl: "/?search=search-python&job=job-python",
    });

    const description = await screen.findByRole("region", { name: "Description" });
    const paragraphs = within(description).getAllByRole("paragraph");
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]).toHaveTextContent(
      '<img src="x" onerror="alert(1)"> Première ligne Seconde ligne',
    );
    expect(paragraphs[0].textContent).toContain("Première ligne\nSeconde ligne");
    expect(paragraphs[1]).toHaveTextContent("Second paragraphe");
    expect(description.querySelector("img")).toBeNull();
  });

  it("affiche un lien externe sécurisé pour chaque source", async () => {
    renderAppWithJobs([JOB], {
      details: {
        ...DETAILS_WITH_DUPLICATE,
        sources: [
          {
            source: "Free-Work",
            url: "https://example.test/free-work/job-python",
            active: true,
          },
          {
            source: "LinkedIn",
            url: "https://example.test/linkedin/job-python",
            active: false,
          },
        ],
      },
      initialUrl: "/?search=search-python&job=job-python",
    });

    const sources = await screen.findByRole("region", { name: "Sources" });
    const links = within(sources).getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      "href",
      "https://example.test/free-work/job-python",
    );
    expect(links[1]).toHaveAttribute(
      "href",
      "https://example.test/linkedin/job-python",
    );
    for (const link of links) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noreferrer");
    }
  });

  it("affiche les compétences et avantages sous forme de listes", async () => {
    renderAppWithJobs([JOB], {
      details: DETAILS_WITH_DUPLICATE,
      initialUrl: "/?search=search-python&job=job-python",
    });

    const skills = await screen.findByRole("region", { name: "Compétences" });
    expect(within(skills).getAllByRole("listitem")).toHaveLength(2);
    expect(skills).toHaveTextContent("Python");
    expect(skills).toHaveTextContent("FastAPI");

    const benefits = screen.getByRole("region", { name: "Avantages" });
    expect(within(benefits).getAllByRole("listitem")).toHaveLength(1);
    expect(benefits).toHaveTextContent("Télétravail");
  });

  it("affiche l’avertissement stale sans masquer les détails", async () => {
    renderAppWithJobs([JOB], {
      details: {
        ...DETAILS_WITH_DUPLICATE,
        cacheState: "stale",
        warning: "La source est indisponible, les détails en cache sont affichés.",
      },
      initialUrl: "/?search=search-python&job=job-python",
    });

    const dialog = await screen.findByRole("dialog", { name: "Détails de l’offre" });
    expect(await within(dialog).findByText("Développeur Python")).toBeVisible();
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "La source est indisponible, les détails en cache sont affichés.",
    );
    expect(within(dialog).queryByRole("alert")).toBeNull();
  });

  it("n’invente pas de description ni de listes lorsqu’elles sont absentes", async () => {
    renderAppWithJobs([JOB], {
      details: {
        ...DETAILS_WITH_DUPLICATE,
        description: null,
        skills: [],
        benefits: [],
        sources: [],
        possibleDuplicates: [],
        updatedAt: "",
      },
      initialUrl: "/?search=search-python&job=job-python",
    });

    const dialog = await screen.findByRole("dialog", { name: "Détails de l’offre" });
    expect(await within(dialog).findByText("Développeur Python")).toBeVisible();
    expect(within(dialog).queryByRole("region", { name: "Description" })).toBeNull();
    expect(within(dialog).queryByRole("region", { name: "Compétences" })).toBeNull();
    expect(within(dialog).queryByRole("region", { name: "Avantages" })).toBeNull();
    expect(within(dialog).queryByRole("region", { name: "Sources" })).toBeNull();
    expect(
      within(dialog).queryByRole("region", {
        name: "Offres similaires possibles",
      }),
    ).toBeNull();
    expect(dialog).not.toHaveTextContent("Non renseigné");
    expect(dialog).not.toHaveTextContent("Détails mis à jour");
  });
});
