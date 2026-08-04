import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { SavedSearch, SearchCreate, SearchUpdate } from "../../api/types";
import { App } from "../../app/App";
import { AppProviders } from "../../app/providers";
import { server } from "../../test/server";

const origin = "http://localhost:3000";

function savedSearch(overrides: Partial<SavedSearch> = {}): SavedSearch {
  return {
    id: "search-backend",
    name: "Backend France",
    keywords: ["backend", "python"],
    title: "Backend engineer",
    location: "France",
    radiusKm: 50,
    contractTypes: ["cdi"],
    experienceLevels: ["senior"],
    workplaceTypes: ["remote"],
    companies: [],
    excludeCompanies: [],
    salaryMin: null,
    sources: ["freework", "linkedin"],
    active: true,
    createdAt: "2026-08-03T08:00:00Z",
    updatedAt: "2026-08-03T09:00:00Z",
    ...overrides,
  };
}

function renderApp(initialUrl = "/") {
  window.history.replaceState({}, "", initialUrl);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const user = userEvent.setup();
  const rendered = render(
    <AppProviders queryClient={queryClient}>
      <App />
    </AppProviders>,
  );
  return { ...rendered, queryClient, user };
}

describe("gestion des recherches enregistrées", () => {
  it("crée une recherche complète, normalise les mots-clés et la sélectionne dans l’URL", async () => {
    let searches: SavedSearch[] = [];
    let received: SearchCreate | undefined;
    const created = savedSearch({ id: "search-created", name: "Backend remote" });
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json(searches)),
      http.post(`${origin}/api/searches`, async ({ request }) => {
        received = (await request.json()) as SearchCreate;
        searches = [created];
        return HttpResponse.json(created, { status: 201 });
      }),
    );
    const { user } = renderApp("/?period=3d");

    expect(await screen.findByText("Aucune recherche active")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Nouvelle recherche" }));

    expect(screen.getByRole("dialog", { name: "Nouvelle recherche enregistrée" })).toBeVisible();
    expect(screen.getByLabelText("Nom")).toHaveFocus();
    await user.type(screen.getByLabelText("Nom"), "Backend remote");
    await user.type(
      screen.getByLabelText("Mots-clés"),
      "backend, python, backend",
    );
    await user.type(screen.getByLabelText("Titre recherché"), "Backend engineer");
    await user.clear(screen.getByLabelText("Lieu"));
    await user.type(screen.getByLabelText("Lieu"), "Paris");
    await user.type(screen.getByLabelText("Rayon en kilomètres"), "25");
    await user.click(screen.getByLabelText("CDI"));
    await user.click(screen.getByLabelText("Freelance"));
    await user.click(screen.getByLabelText("Sur site"));
    await user.click(screen.getByLabelText("Télétravail"));
    await user.click(screen.getByLabelText("Début de carrière"));
    await user.click(screen.getByLabelText("Senior"));
    await user.click(screen.getByLabelText("Free-Work"));
    await user.click(screen.getByLabelText("LinkedIn"));
    await user.click(screen.getByLabelText("France Travail"));
    await user.click(screen.getByLabelText("Welcome to the Jungle"));
    expect(screen.getByLabelText("Recherche active")).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Enregistrer la recherche" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("combobox", { name: "Recherche enregistrée" })).toHaveValue(
      "search-created",
    );
    expect(new URLSearchParams(window.location.search).get("search")).toBe(
      "search-created",
    );
    expect(new URLSearchParams(window.location.search).get("period")).toBe("3d");
    expect(received).toEqual({
      name: "Backend remote",
      keywords: ["backend", "python"],
      title: "Backend engineer",
      location: "Paris",
      radiusKm: 25,
      contractTypes: ["cdi", "freelance"],
      experienceLevels: ["internship", "senior"],
      workplaceTypes: ["on_site", "remote"],
      sources: ["freework", "linkedin", "francetravail", "wttj"],
      active: true,
    });
  });

  it("préserve un lien profond valide, les autres paramètres et répare une sélection disparue", async () => {
    const first = savedSearch({ id: "search-first", name: "Première recherche" });
    const second = savedSearch({ id: "search-second", name: "Deuxième recherche" });
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json([first, second])),
    );
    const { queryClient, user } = renderApp(
      "/?search=search-second&period=7d&source=freework&search=stale&source=linkedin",
    );
    const selector = await screen.findByRole("combobox", {
      name: "Recherche enregistrée",
    });

    await waitFor(() => expect(selector).toHaveValue("search-second"));
    expect(new URLSearchParams(window.location.search).getAll("search")).toEqual([
      "search-second",
    ]);
    expect(new URLSearchParams(window.location.search).getAll("source")).toEqual([
      "freework",
      "linkedin",
    ]);
    await user.selectOptions(selector, "search-first");
    expect(window.location.search).toContain("search=search-first");
    expect(window.location.search).toContain("period=7d");
    expect(window.location.search).toContain("source=freework");

    await user.selectOptions(selector, "search-second");
    act(() => queryClient.setQueryData(["searches"], [first]));
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get("search")).toBe(
        "search-first",
      ),
    );
    expect(selector).toHaveValue("search-first");
  });

  it("envoie un PATCH limité aux champs touchés et traduit les champs effacés en null", async () => {
    let current = savedSearch();
    let received: SearchUpdate | undefined;
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json([current])),
      http.patch(`${origin}/api/searches/${current.id}`, async ({ request }) => {
        received = (await request.json()) as SearchUpdate;
        current = { ...current, title: null, radiusKm: null };
        return HttpResponse.json(current);
      }),
    );
    const { user } = renderApp(`/?search=${current.id}`);
    await screen.findByRole("combobox", { name: "Recherche enregistrée" });

    await user.click(screen.getByRole("button", { name: "Modifier la recherche" }));
    expect(screen.getByLabelText("Nom")).toHaveValue("Backend France");
    expect(screen.getByLabelText("Free-Work")).toBeChecked();
    await user.clear(screen.getByLabelText("Titre recherché"));
    await user.clear(screen.getByLabelText("Rayon en kilomètres"));
    await user.click(
      screen.getByRole("button", { name: "Enregistrer les modifications" }),
    );

    await waitFor(() => expect(received).toEqual({ title: null, radiusKm: null }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get("search")).toBe(current.id);
  });

  it("préserve les valeurs historiques inconnues lors d’une modification sans rapport", async () => {
    const legacy = savedSearch({
      id: "search-legacy",
      name: "Ancienne recherche",
      contractTypes: ["legacy-contract", "cdi", "cdi"],
      experienceLevels: ["expert"],
      workplaceTypes: ["somewhere"],
      sources: ["legacy-source"],
    });
    let received: SearchUpdate | undefined;
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json([legacy])),
      http.patch(`${origin}/api/searches/${legacy.id}`, async ({ request }) => {
        received = (await request.json()) as SearchUpdate;
        return HttpResponse.json({ ...legacy, name: "Recherche renommée" });
      }),
    );
    const { user } = renderApp(`/?search=${legacy.id}`);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Modifier la recherche" }),
      ).toBeEnabled(),
    );

    await user.click(screen.getByRole("button", { name: "Modifier la recherche" }));
    await user.click(screen.getByLabelText("CDI"));
    await user.click(screen.getByLabelText("CDI"));
    expect(
      screen.getByRole("button", { name: "Enregistrer les modifications" }),
    ).toBeDisabled();
    await user.clear(screen.getByLabelText("Nom"));
    await user.type(screen.getByLabelText("Nom"), "Recherche renommée");
    await user.click(
      screen.getByRole("button", { name: "Enregistrer les modifications" }),
    );

    await waitFor(() => expect(received).toEqual({ name: "Recherche renommée" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("suspend puis réactive la recherche choisie sans perdre la sélection", async () => {
    const first = savedSearch({ id: "search-first", name: "Backend" });
    const second = savedSearch({ id: "search-second", name: "Data" });
    let searches = [first, second];
    const received: SearchUpdate[] = [];
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json(searches)),
      http.patch(`${origin}/api/searches/${first.id}`, async ({ request }) => {
        const payload = (await request.json()) as SearchUpdate;
        received.push(payload);
        const updated = { ...first, active: payload.active ?? first.active };
        searches = [updated, second];
        return HttpResponse.json(updated);
      }),
    );
    const { user } = renderApp(`/?search=${first.id}`);
    const selector = await screen.findByRole("combobox", {
      name: "Recherche enregistrée",
    });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Suspendre la recherche" }),
      ).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Suspendre la recherche" }));

    await waitFor(() => expect(received).toEqual([{ active: false }]));
    expect(selector).toHaveValue(first.id);
    expect(new URLSearchParams(window.location.search).get("search")).toBe(first.id);
    expect(within(selector).getByRole("option", { name: "Backend (suspendue)" })).toBeVisible();
    expect(await screen.findByText("La recherche « Backend » est suspendue.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Réactiver la recherche" }));
    await waitFor(() =>
      expect(received).toEqual([{ active: false }, { active: true }]),
    );
    expect(selector).toHaveValue(first.id);
    expect(await screen.findByText("La recherche « Backend » est réactivée.")).toBeVisible();
  });

  it("valide en français les champs requis, les sources et le rayon zéro sans appeler l’API", async () => {
    let createCalls = 0;
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json([])),
      http.post(`${origin}/api/searches`, () => {
        createCalls += 1;
        return HttpResponse.json(savedSearch(), { status: 201 });
      }),
    );
    const { user } = renderApp();
    await screen.findByText("Aucune recherche active");
    await user.click(screen.getByRole("button", { name: "Nouvelle recherche" }));

    await user.click(screen.getByRole("button", { name: "Enregistrer la recherche" }));
    expect(screen.getByText("Saisissez un nom pour cette recherche.")).toBeVisible();
    expect(screen.getByLabelText("Nom")).toHaveFocus();
    expect(screen.getByText("Ajoutez au moins un mot-clé.")).toBeVisible();
    expect(screen.getByText("Sélectionnez au moins une source.")).toBeVisible();

    await user.type(screen.getByLabelText("Nom"), "Backend");
    await user.type(screen.getByLabelText("Mots-clés"), "python");
    await user.click(screen.getByLabelText("Free-Work"));
    await user.type(screen.getByLabelText("Rayon en kilomètres"), "0");
    await user.click(screen.getByRole("button", { name: "Enregistrer la recherche" }));

    expect(
      screen.getByText("Le rayon doit être un nombre entier supérieur ou égal à 1."),
    ).toBeVisible();
    expect(screen.getByLabelText("Rayon en kilomètres")).toHaveFocus();
    expect(createCalls).toBe(0);
  });

  it("gère le focus, le piège clavier, Échap et la restauration vers le déclencheur", async () => {
    server.use(http.get(`${origin}/api/searches`, () => HttpResponse.json([])));
    const { user } = renderApp();
    await screen.findByText("Aucune recherche active");
    const trigger = screen.getByRole("button", { name: "Nouvelle recherche" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Nouvelle recherche enregistrée" });
    const close = screen.getByRole("button", { name: "Fermer l’éditeur" });
    const submit = screen.getByRole("button", { name: "Enregistrer la recherche" });
    expect(screen.getByLabelText("Nom")).toHaveFocus();

    close.focus();
    await user.tab({ shift: true });
    expect(submit).toHaveFocus();

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    fireEvent.click(screen.getByRole("dialog"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("refuse toute fermeture accidentelle pendant l’enregistrement", async () => {
    let releaseRequest: (() => void) | undefined;
    const pending = new Promise<void>((resolve) => {
      releaseRequest = resolve;
    });
    let searches: SavedSearch[] = [];
    const created = savedSearch({ id: "search-pending" });
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json(searches)),
      http.post(`${origin}/api/searches`, async () => {
        await pending;
        searches = [created];
        return HttpResponse.json(created, { status: 201 });
      }),
    );
    const { user } = renderApp();
    await screen.findByText("Aucune recherche active");
    await user.click(screen.getByRole("button", { name: "Nouvelle recherche" }));
    await user.type(screen.getByLabelText("Nom"), "Backend");
    await user.type(screen.getByLabelText("Mots-clés"), "python");
    await user.click(screen.getByLabelText("Free-Work"));
    await user.click(screen.getByRole("button", { name: "Enregistrer la recherche" }));

    const dialog = screen.getByRole("dialog");
    expect(await screen.findByRole("button", { name: "Enregistrement en cours…" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    fireEvent.click(dialog);
    await user.click(screen.getByRole("button", { name: "Fermer l’éditeur" }));
    expect(screen.getByRole("dialog")).toBeVisible();

    act(() => releaseRequest?.());
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("sérialise une double soumission déclenchée dans le même tour d’événement", async () => {
    let releaseRequest: (() => void) | undefined;
    const pending = new Promise<void>((resolve) => {
      releaseRequest = resolve;
    });
    let createCalls = 0;
    const created = savedSearch({ id: "search-once" });
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json([])),
      http.post(`${origin}/api/searches`, async () => {
        createCalls += 1;
        await pending;
        return HttpResponse.json(created, { status: 201 });
      }),
    );
    const { user } = renderApp();
    await screen.findByText("Aucune recherche active");
    await user.click(screen.getByRole("button", { name: "Nouvelle recherche" }));
    await user.type(screen.getByLabelText("Nom"), "Backend");
    await user.type(screen.getByLabelText("Mots-clés"), "python");
    await user.click(screen.getByLabelText("Free-Work"));
    const submit = screen.getByRole("button", { name: "Enregistrer la recherche" });
    const form = submit.closest("form");
    expect(form).not.toBeNull();

    fireEvent.submit(form!);
    fireEvent.submit(form!);

    await waitFor(() => expect(createCalls).toBe(1));
    act(() => releaseRequest?.());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("utilise immédiatement le DTO créé même si le rechargement de fond reste bloqué", async () => {
    let releaseReload: (() => void) | undefined;
    const reloadGate = new Promise<void>((resolve) => {
      releaseReload = resolve;
    });
    let getCalls = 0;
    const created = savedSearch({ id: "search-race", name: "Résultat serveur" });
    server.use(
      http.get(`${origin}/api/searches`, async () => {
        getCalls += 1;
        if (getCalls === 1) {
          return HttpResponse.json([]);
        }
        await reloadGate;
        return HttpResponse.json([created]);
      }),
      http.post(`${origin}/api/searches`, () =>
        HttpResponse.json(created, { status: 201 }),
      ),
    );
    const { user } = renderApp();
    await screen.findByText("Aucune recherche active");
    await user.click(screen.getByRole("button", { name: "Nouvelle recherche" }));
    await user.type(screen.getByLabelText("Nom"), "Résultat serveur");
    await user.type(screen.getByLabelText("Mots-clés"), "python");
    await user.click(screen.getByLabelText("Free-Work"));
    await user.click(screen.getByRole("button", { name: "Enregistrer la recherche" }));
    await waitFor(() => expect(getCalls).toBe(2));

    try {
      await waitFor(
        () => expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
        { timeout: 250 },
      );
      expect(screen.getByRole("combobox", { name: "Recherche enregistrée" })).toHaveValue(
        created.id,
      );
    } finally {
      act(() => releaseReload?.());
    }

    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Recherche enregistrée" }),
      ).toHaveValue(created.id),
    );
  });

  it("restaure le focus vers le sélecteur après une création depuis le CTA vide", async () => {
    const created = savedSearch({ id: "search-focus", name: "Backend" });
    let searches: SavedSearch[] = [];
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json(searches)),
      http.post(`${origin}/api/searches`, () => {
        searches = [created];
        return HttpResponse.json(created, { status: 201 });
      }),
    );
    const { user } = renderApp();
    expect(await screen.findByText("Aucune recherche active")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "Créer ma première recherche" }),
    );
    await user.type(screen.getByLabelText("Nom"), "Backend");
    await user.type(screen.getByLabelText("Mots-clés"), "python");
    await user.click(screen.getByLabelText("Free-Work"));
    await user.click(screen.getByRole("button", { name: "Enregistrer la recherche" }));

    const selector = await screen.findByRole("combobox", {
      name: "Recherche enregistrée",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(selector).toHaveFocus();
  });

  it("traduit une erreur serveur non structurée sans exposer son texte anglais", async () => {
    server.use(
      http.get(`${origin}/api/searches`, () => HttpResponse.json([])),
      http.post(`${origin}/api/searches`, () =>
        HttpResponse.text("Internal Server Error", { status: 500 }),
      ),
    );
    const { user } = renderApp();
    await screen.findByText("Aucune recherche active");
    await user.click(screen.getByRole("button", { name: "Nouvelle recherche" }));
    await user.type(screen.getByLabelText("Nom"), "Backend");
    await user.type(screen.getByLabelText("Mots-clés"), "python");
    await user.click(screen.getByLabelText("Free-Work"));
    await user.click(screen.getByRole("button", { name: "Enregistrer la recherche" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Le service local a rencontré une erreur. Réessayez dans un instant.",
    );
    expect(alert).not.toHaveTextContent("Internal Server Error");
  });

  it("affiche des erreurs françaises et permet de relancer le chargement ou corriger le formulaire", async () => {
    let listFails = true;
    server.use(
      http.get(`${origin}/api/searches`, () =>
        listFails
          ? HttpResponse.json({ detail: "Base indisponible" }, { status: 503 })
          : HttpResponse.json([]),
      ),
      http.post(`${origin}/api/searches`, () =>
        HttpResponse.json(
          {
            detail: [
              {
                type: "value_error",
                loc: ["body", "name"],
                msg: "Value error",
                input: "Backend",
              },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    const { user } = renderApp();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Impossible de charger les recherches enregistrées.",
    );
    listFails = false;
    await user.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByText("Aucune recherche active")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Nouvelle recherche" }));
    await user.type(screen.getByLabelText("Nom"), "Backend");
    await user.type(screen.getByLabelText("Mots-clés"), "python");
    await user.click(screen.getByLabelText("Free-Work"));
    await user.click(screen.getByRole("button", { name: "Enregistrer la recherche" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Les informations saisies ne sont pas valides. Vérifiez les champs du formulaire.",
    );
    expect(screen.getByRole("dialog")).toBeVisible();
  });
});
