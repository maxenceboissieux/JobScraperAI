import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { JobCard, SavedSearch } from "../../api/types";
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
  options: { initialUrl?: string; total?: number } = {},
) {
  window.history.replaceState({}, "", options.initialUrl ?? "/?search=search-python");
  server.use(
    http.get(`${origin}/api/searches`, () => HttpResponse.json([savedSearch])),
    http.get(`${origin}/api/jobs`, ({ request }) => {
      const url = new URL(request.url);
      return HttpResponse.json({
        items: jobs,
        total: options.total ?? jobs.length,
        limit: Number(url.searchParams.get("limit")),
        offset: Number(url.searchParams.get("offset")),
      });
    }),
  );
  return renderApplication();
}

function renderApplication() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
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

describe("grille des offres", () => {
  it("affiche les sources et le doublon possible", async () => {
    renderAppWithJobs([POSSIBLE_DUPLICATE_JOB]);

    expect(await screen.findByText("Développeur Python")).toBeVisible();
    const card = screen.getByRole("button", { name: "Voir l’offre Développeur Python" });
    expect(within(card).getByText("Free-Work")).toBeVisible();
    expect(within(card).getByText("LinkedIn")).toBeVisible();
    expect(within(card).getByText("Doublon possible")).toBeVisible();
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
