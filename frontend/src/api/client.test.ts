// @vitest-environment node

import { delay, http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./client";
import type {
  JobDetails,
  JobsPage,
  SavedSearch,
  SyncRun,
} from "./types";
import { server } from "../test/server";

const origin = "http://localhost:3000";

const savedSearch: SavedSearch = {
  id: "search-1",
  name: "Backend",
  keywords: ["python"],
  title: null,
  location: "France",
  radiusKm: null,
  contractTypes: ["cdi"],
  experienceLevels: ["senior"],
  workplaceTypes: ["remote"],
  companies: [],
  excludeCompanies: [],
  salaryMin: 0,
  maxResults: 500,
  sources: ["freework"],
  active: false,
  createdAt: "2026-08-03T08:00:00Z",
  updatedAt: "2026-08-03T09:00:00Z",
};

const jobDetails: JobDetails = {
  id: "job-1",
  title: "Développeur C++",
  company: "Acme",
  location: "Île-de-France",
  salaryMin: 0,
  salaryMax: null,
  salaryCurrency: "EUR",
  contractType: "cdi",
  experienceLevel: "senior",
  remote: false,
  postedAt: null,
  viewedAt: null,
  sources: [{ source: "freework", url: "https://example.test/job", active: true }],
  duplicateState: "none",
  possibleDuplicates: [],
  description: null,
  skills: ["C++"],
  benefits: [],
  cacheState: "fresh",
  updatedAt: "2026-08-03T09:00:00Z",
  warning: null,
};

const syncRun: SyncRun = {
  id: "run-1",
  savedSearchId: "search-1",
  status: "pending",
  requestedSources: ["freework"],
  createdAt: "2026-08-03T09:00:00Z",
  startedAt: null,
  finishedAt: null,
  sources: [
    {
      source: "freework",
      status: "pending",
      offersSeen: 0,
      offersPersisted: 0,
      errorMessage: null,
      startedAt: null,
      finishedAt: null,
    },
  ],
};

describe("api", () => {
  it("préserve le filtre actif faux pour lister les recherches", async () => {
    server.use(
      http.get(`${origin}/api/searches`, ({ request }) => {
        expect(new URL(request.url).search).toBe("?active=false");
        return HttpResponse.json([savedSearch]);
      }),
    );

    await expect(api.getSearches({ active: false })).resolves.toEqual([
      savedSearch,
    ]);
  });

  it("envoie le payload de création en camelCase avec les en-têtes JSON", async () => {
    server.use(
      http.post(`${origin}/api/searches`, async ({ request }) => {
        expect(request.headers.get("accept")).toBe("application/json");
        expect(request.headers.get("content-type")).toBe("application/json");
        expect(await request.json()).toEqual({
          name: "Backend",
          keywords: ["python"],
          radiusKm: null,
          salaryMin: 0,
          sources: ["freework"],
          active: false,
        });
        return HttpResponse.json(savedSearch, { status: 201 });
      }),
    );

    await expect(
      api.createSearch({
        name: "Backend",
        keywords: ["python"],
        radiusKm: null,
        salaryMin: 0,
        sources: ["freework"],
        active: false,
      }),
    ).resolves.toEqual(savedSearch);
  });

  it("encode l’identifiant et conserve les valeurs nulles du patch", async () => {
    server.use(
      http.patch(`${origin}/api/searches/id%2Flegacy`, async ({ request }) => {
        expect(await request.json()).toEqual({ title: null, salaryMin: 0 });
        return HttpResponse.json(savedSearch);
      }),
    );

    await expect(
      api.updateSearch("id/legacy", { title: null, salaryMin: 0 }),
    ).resolves.toEqual(savedSearch);
  });

  it("encode les filtres d’offres avec les noms et répétitions FastAPI", async () => {
    const page: JobsPage = { items: [], total: 0, limit: 24, offset: 0 };
    server.use(
      http.get(`${origin}/api/jobs`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        expect(params.get("savedSearchId")).toBe("search/été");
        expect(params.get("period")).toBe("3d");
        expect(params.get("query")).toBe("C++ & Rust");
        expect(params.getAll("location")).toEqual(["Paris", "Lyon & alentours"]);
        expect(params.getAll("contract")).toEqual(["cdi", "freelance"]);
        expect(params.get("remote")).toBe("false");
        expect(params.getAll("experience")).toEqual(["senior", "lead"]);
        expect(params.get("salaryMin")).toBe("0");
        expect(params.getAll("company")).toEqual(["A&B", "Société Générale"]);
        expect(params.getAll("source")).toEqual(["freework", "linkedin"]);
        expect(params.getAll("skill")).toEqual(["C++", "Node.js"]);
        expect(params.get("duplicateState")).toBe("possible");
        expect(params.get("sort")).toBe("relevance");
        expect(params.get("limit")).toBe("24");
        expect(params.get("offset")).toBe("0");
        expect([...params.keys()]).not.toContain("locations");
        expect([...params.keys()]).not.toContain("sources");
        return HttpResponse.json(page);
      }),
    );

    await expect(
      api.getJobs({
        savedSearchId: "search/été",
        period: "3d",
        query: "C++ & Rust",
        locations: ["Paris", "Lyon & alentours"],
        contracts: ["cdi", "freelance"],
        remote: false,
        experience: ["senior", "lead"],
        salaryMin: 0,
        companies: ["A&B", "Société Générale"],
        sources: ["freework", "linkedin"],
        skills: ["C++", "Node.js"],
        duplicateState: "possible",
        sort: "relevance",
        limit: 24,
        offset: 0,
      }),
    ).resolves.toEqual(page);
  });

  it("récupère un détail avec un identifiant encodé", async () => {
    server.use(
      http.get(`${origin}/api/jobs/job%2F1`, () => HttpResponse.json(jobDetails)),
    );

    await expect(api.getJob("job/1")).resolves.toEqual(jobDetails);
  });

  it("démarre une synchronisation avec le sous-ensemble demandé", async () => {
    server.use(
      http.post(`${origin}/api/syncs`, async ({ request }) => {
        expect(await request.json()).toEqual({
          savedSearchId: "search-1",
          sources: ["freework"],
        });
        return HttpResponse.json(syncRun, { status: 202 });
      }),
    );

    await expect(
      api.startSync({ savedSearchId: "search-1", sources: ["freework"] }),
    ).resolves.toEqual(syncRun);
  });

  it("préserve un sous-ensemble de sources explicitement nul", async () => {
    server.use(
      http.post(`${origin}/api/syncs`, async ({ request }) => {
        expect(await request.json()).toEqual({
          savedSearchId: "search-1",
          sources: null,
        });
        return HttpResponse.json(syncRun, { status: 202 });
      }),
    );

    await expect(
      api.startSync({ savedSearchId: "search-1", sources: null }),
    ).resolves.toEqual(syncRun);
  });

  it("relance une seule source sur le chemin encodé", async () => {
    server.use(
      http.post(`${origin}/api/syncs/run%2F1/retry`, async ({ request }) => {
        expect(await request.json()).toEqual({ source: "linkedin" });
        return HttpResponse.json(syncRun, { status: 202 });
      }),
    );

    await expect(api.retrySyncSource("run/1", "linkedin")).resolves.toEqual(
      syncRun,
    );
  });

  it("récupère la dernière synchronisation de la recherche demandée", async () => {
    server.use(
      http.get(`${origin}/api/syncs/latest`, ({ request }) => {
        expect(new URL(request.url).search).toBe(
          "?savedSearchId=search%2F%C3%A9t%C3%A9",
        );
        return HttpResponse.json(syncRun);
      }),
    );

    await expect(
      api.getLatestSync({ savedSearchId: "search/été" }),
    ).resolves.toEqual(syncRun);
  });

  it.each([
    ["JSON null", HttpResponse.json(null)],
    ["statut 204", new HttpResponse(null, { status: 204 })],
  ])("retourne null pour la dernière synchronisation absente (%s)", async (_, response) => {
    server.use(http.get(`${origin}/api/syncs/latest`, () => response));

    await expect(api.getLatestSync()).resolves.toBeNull();
  });

  it("rejette un statut 204 sur un endpoint à réponse obligatoire", async () => {
    server.use(
      http.get(
        `${origin}/api/jobs/job-1`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );

    await expect(api.getJob("job-1")).rejects.toMatchObject({
      status: 204,
      detail: "La réponse du serveur est vide.",
    });
  });

  it("rejette un corps vide sur un endpoint à réponse obligatoire", async () => {
    server.use(
      http.post(
        `${origin}/api/searches`,
        () => new HttpResponse(null, { status: 201 }),
      ),
    );

    await expect(
      api.createSearch({
        name: "Backend",
        keywords: ["python"],
        sources: ["freework"],
      }),
    ).rejects.toMatchObject({
      status: 201,
      detail: "La réponse du serveur est vide.",
    });
  });

  it("rejette JSON null sur un endpoint à réponse obligatoire", async () => {
    server.use(
      http.post(`${origin}/api/syncs`, () =>
        HttpResponse.json(null, { status: 202 }),
      ),
    );

    await expect(
      api.startSync({ savedSearchId: "search-1" }),
    ).rejects.toMatchObject({
      status: 202,
      detail: "La réponse du serveur est vide.",
    });
  });

  it("expose le détail FastAPI et le statut HTTP dans ApiError", async () => {
    server.use(
      http.get(`${origin}/api/jobs/missing`, () =>
        HttpResponse.json({ detail: "L’offre demandée n’existe pas." }, { status: 404 }),
      ),
    );

    const error = await api.getJob("missing").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 404,
      detail: "L’offre demandée n’existe pas.",
      message: "L’offre demandée n’existe pas.",
    });
  });

  it("conserve les erreurs de validation structurées de FastAPI", async () => {
    const detail = [
      {
        type: "missing",
        loc: ["body", "name"],
        msg: "Field required",
        input: {},
      },
    ];
    server.use(
      http.post(`${origin}/api/searches`, () =>
        HttpResponse.json({ detail }, { status: 422 }),
      ),
    );

    const error = await api
      .createSearch({ name: "Backend", keywords: ["python"], sources: ["freework"] })
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, detail });
  });

  it("utilise le texte d’une erreur HTTP non JSON", async () => {
    server.use(
      http.get(`${origin}/api/syncs/latest`, () =>
        new HttpResponse("Passerelle indisponible", {
          status: 502,
          headers: { "Content-Type": "text/plain" },
        }),
      ),
    );

    const error = await api.getLatestSync().catch((caught: unknown) => caught);

    expect(error).toMatchObject({
      status: 502,
      detail: "Passerelle indisponible",
      message: "Passerelle indisponible",
    });
  });

  it("convertit une panne réseau en ApiError sans statut HTTP", async () => {
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.error()),
    );

    const error = await api.getSearches().catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 0,
      detail: "Impossible de joindre le serveur.",
    });
  });

  it("transmet AbortSignal et préserve AbortError pour annuler la requête", async () => {
    server.use(
      http.get(`${origin}/api/searches`, async () => {
        await delay("infinite");
        return HttpResponse.json([]);
      }),
    );
    const controller = new AbortController();
    const request = api.getSearches({ signal: controller.signal });

    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });

  it("écarte un AbortSignal d’un realm incompatible sans perdre la requête", async () => {
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json([savedSearch])),
    );
    const NativeRequest = globalThis.Request;
    const CrossRealmRejectingRequest = function (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) {
      if (init?.signal) {
        throw new TypeError("AbortSignal d’un autre realm");
      }
      return new NativeRequest(input, init);
    } as unknown as typeof Request;
    CrossRealmRejectingRequest.prototype = NativeRequest.prototype;
    vi.stubGlobal("Request", CrossRealmRejectingRequest);

    try {
      await expect(
        api.getSearches({ signal: new AbortController().signal }),
      ).resolves.toEqual([savedSearch]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("signale une réponse JSON de succès invalide", async () => {
    server.use(
      http.post(`${origin}/api/searches`, () =>
        new HttpResponse("{broken", {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const error = await api
      .createSearch({ name: "Backend", keywords: ["python"], sources: ["freework"] })
      .catch((caught: unknown) => caught);

    expect(error).toMatchObject({
      status: 201,
      detail: "La réponse du serveur est invalide.",
    });
  });
});
