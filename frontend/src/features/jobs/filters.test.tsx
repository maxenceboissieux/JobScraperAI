import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { SavedSearch } from "../../api/types";
import { App } from "../../app/App";
import { AppProviders } from "../../app/providers";
import { server } from "../../test/server";
import { useJobFilters } from "./useJobFilters";

const origin = "http://localhost:3000";

const savedSearch: SavedSearch = {
  id: "recherche-1",
  name: "Backend France",
  keywords: ["backend"],
  title: null,
  location: "France",
  radiusKm: null,
  contractTypes: ["cdi"],
  experienceLevels: ["senior"],
  workplaceTypes: ["remote"],
  companies: [],
  excludeCompanies: [],
  salaryMin: null,
  sources: ["freework"],
  active: true,
  createdAt: "2026-08-03T08:00:00Z",
  updatedAt: "2026-08-03T09:00:00Z",
};

function FilterHarness() {
  const {
    filters,
    activeCount,
    setFilter,
    clearFilters,
    setOffset,
    queryDraft,
    setQueryDraft,
  } = useJobFilters();

  return (
    <>
      <output aria-label="Filtres API">{JSON.stringify(filters)}</output>
      <output aria-label="Nombre de filtres actifs">{activeCount}</output>
      <label>
        Recherche libre
        <input
          value={queryDraft}
          onChange={(event) => setQueryDraft(event.currentTarget.value)}
        />
      </label>
      <button type="button" onClick={() => setFilter("period", "3d")}>
        Choisir 3 jours
      </button>
      <button type="button" onClick={clearFilters}>
        Effacer
      </button>
      <button type="button" onClick={() => setOffset(48)}>
        Page 3
      </button>
      <button type="button" onClick={() => setFilter("sources", ["linkedin"])}>
        LinkedIn seulement
      </button>
    </>
  );
}

function renderFilters(initialUrl: string) {
  window.history.replaceState({}, "", initialUrl);
  const user = userEvent.setup();
  return {
    user,
    ...render(
      <BrowserRouter>
        <FilterHarness />
      </BrowserRouter>,
    ),
  };
}

function renderedFilters() {
  return JSON.parse(screen.getByLabelText("Filtres API").textContent ?? "null") as {
    savedSearchId?: string;
    period: string;
    query?: string;
    locations?: string[];
    contracts?: string[];
    remote?: boolean;
    experience?: string[];
    salaryMin?: number;
    companies?: string[];
    sources?: string[];
    skills?: string[];
    duplicateState?: string;
    sort?: string;
    limit: number;
    offset: number;
  };
}

function renderApplication(initialUrl: string) {
  window.history.replaceState({}, "", initialUrl);
  server.use(
    http.get(`${origin}/api/searches`, () => HttpResponse.json([savedSearch])),
  );
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const user = userEvent.setup();
  return {
    user,
    ...render(
      <AppProviders queryClient={queryClient}>
        <App />
      </AppProviders>,
    ),
  };
}

describe("filtres d’offres pilotés par l’URL", () => {
  it("applique les valeurs par défaut et canonise les doublons, vides et valeurs invalides", async () => {
    renderFilters(
      "/?search=recherche-1&trace=a&trace=b&period=inconnue&period=7d&q=%20&lieu=Paris&lieu=&lieu=Paris&contrat=cdi&contrat=obsolete&remote=peut-etre&salaire=-1&source=freework&source=freework&source=inconnue&doublon=autre&tri=ancien",
    );

    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.getAll("period")).toEqual(["3d"]);
      expect(params.getAll("lieu")).toEqual(["Paris"]);
      expect(params.getAll("contrat")).toEqual(["cdi"]);
      expect(params.getAll("source")).toEqual(["freework"]);
      expect(params.has("q")).toBe(false);
      expect(params.has("remote")).toBe(false);
      expect(params.has("salaire")).toBe(false);
      expect(params.has("doublon")).toBe(false);
      expect(params.has("tri")).toBe(false);
      expect(params.get("search")).toBe("recherche-1");
      expect(params.getAll("trace")).toEqual(["a", "b"]);
    });
    expect(renderedFilters()).toEqual({
      savedSearchId: "recherche-1",
      period: "3d",
      locations: ["Paris"],
      contracts: ["cdi"],
      sources: ["freework"],
      sort: "date",
      limit: 24,
      offset: 0,
    });
  });

  it("préserve les tableaux ordonnés, false et le salaire zéro dans le contrat API", async () => {
    renderFilters(
      "/?period=7d&q=Rust&lieu=Lyon&lieu=Paris&contrat=freelance&remote=false&experience=senior&salaire=0&entreprise=Acme&source=linkedin&source=freework&competence=Rust&doublon=possible&tri=relevance",
    );

    await waitFor(() => expect(renderedFilters().period).toBe("7d"));
    expect(renderedFilters()).toEqual({
      period: "7d",
      query: "Rust",
      locations: ["Lyon", "Paris"],
      contracts: ["freelance"],
      remote: false,
      experience: ["senior"],
      salaryMin: 0,
      companies: ["Acme"],
      sources: ["linkedin", "freework"],
      skills: ["Rust"],
      duplicateState: "possible",
      sort: "relevance",
      limit: 24,
      offset: 0,
    });
    expect(screen.getByLabelText("Nombre de filtres actifs")).toHaveTextContent("10");
  });

  it("change la période puis efface seulement les filtres en préservant recherche et paramètres étrangers", async () => {
    const { user } = renderFilters(
      "/?search=recherche-1&period=24h&source=freework&trace=a&trace=b",
    );

    await user.click(screen.getByRole("button", { name: "Choisir 3 jours" }));
    expect(new URLSearchParams(window.location.search).get("period")).toBe("3d");
    expect(new URLSearchParams(window.location.search).get("source")).toBe("freework");

    await user.click(screen.getByRole("button", { name: "Effacer" }));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("period")).toBe("3d");
    expect(params.get("search")).toBe("recherche-1");
    expect(params.getAll("trace")).toEqual(["a", "b"]);
    expect(params.has("source")).toBe(false);
    expect(screen.getByLabelText("Nombre de filtres actifs")).toHaveTextContent("0");
  });

  it("réinitialise l’offset interne seulement lors d’un changement de filtre effectif", async () => {
    const { user } = renderFilters("/?period=3d&source=freework");

    await user.click(screen.getByRole("button", { name: "Page 3" }));
    expect(renderedFilters().offset).toBe(48);
    await user.click(screen.getByRole("button", { name: "Choisir 3 jours" }));
    expect(renderedFilters().offset).toBe(48);
    await user.click(screen.getByRole("button", { name: "LinkedIn seulement" }));
    expect(renderedFilters().offset).toBe(0);
  });

  it("attend 250 ms avant d’écrire la recherche libre dans l’URL", async () => {
    vi.useFakeTimers();
    try {
      renderFilters("/?period=3d&q=python");
      const query = screen.getByLabelText("Recherche libre");

      fireEvent.change(query, { target: { value: "rust" } });
      expect(new URLSearchParams(window.location.search).get("q")).toBe("python");
      act(() => vi.advanceTimersByTime(249));
      expect(new URLSearchParams(window.location.search).get("q")).toBe("python");
      act(() => vi.advanceTimersByTime(1));
      expect(new URLSearchParams(window.location.search).get("q")).toBe("rust");
    } finally {
      vi.useRealTimers();
    }
  });

  it("resynchronise le brouillon lorsqu’une navigation fournit un nouveau lien profond", async () => {
    renderFilters("/?period=3d&q=python");
    expect(screen.getByLabelText("Recherche libre")).toHaveValue("python");

    act(() => {
      window.history.pushState({}, "", "/?period=3d&q=rust");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    await waitFor(() =>
      expect(screen.getByLabelText("Recherche libre")).toHaveValue("rust"),
    );
  });

  it("annule une écriture différée lorsque le filtre est démonté", () => {
    vi.useFakeTimers();
    try {
      const { unmount } = renderFilters("/?period=3d&q=python");
      fireEvent.change(screen.getByLabelText("Recherche libre"), {
        target: { value: "rust" },
      });

      unmount();
      act(() => vi.advanceTimersByTime(250));
      expect(new URLSearchParams(window.location.search).get("q")).toBe("python");
    } finally {
      vi.useRealTimers();
    }
  });

  it("annule une recherche différée lorsque les filtres sont effacés", () => {
    vi.useFakeTimers();
    try {
      renderFilters("/?period=3d");
      fireEvent.change(screen.getByLabelText("Recherche libre"), {
        target: { value: "rust" },
      });

      fireEvent.click(screen.getByRole("button", { name: "Effacer" }));
      act(() => vi.advanceTimersByTime(250));

      expect(new URLSearchParams(window.location.search).has("q")).toBe(false);
      expect(screen.getByLabelText("Recherche libre")).toHaveValue("");
    } finally {
      vi.useRealTimers();
    }
  });

});

describe("barre de filtres française", () => {
  it("change la période et efface les filtres sans perdre la recherche ni les paramètres étrangers", async () => {
    const { user } = renderApplication(
      "/?search=recherche-1&period=24h&source=freework&trace=a&trace=b",
    );
    await screen.findByRole("combobox", { name: "Recherche enregistrée" });

    const oneDay = screen.getByRole("button", { name: "24 h" });
    expect(oneDay).toHaveAttribute("aria-pressed", "true");
    expect(oneDay).toHaveAttribute("aria-current", "true");
    await user.click(screen.getByRole("button", { name: "3 jours" }));
    expect(new URLSearchParams(window.location.search).get("period")).toBe("3d");

    await user.click(screen.getByRole("button", { name: "Effacer les filtres" }));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("period")).toBe("3d");
    expect(params.get("search")).toBe("recherche-1");
    expect(params.getAll("trace")).toEqual(["a", "b"]);
    expect(params.has("source")).toBe(false);
  });

  it("offre un panneau repliable nommé, compté et composé de contrôles sémantiques", async () => {
    const { user } = renderApplication(
      "/?search=recherche-1&period=3d&remote=false&salaire=0&tri=relevance",
    );
    await screen.findByRole("combobox", { name: "Recherche enregistrée" });

    const disclosure = screen.getByRole("button", {
      name: "Afficher les filtres, 2 actifs",
    });
    expect(disclosure).toHaveAttribute("aria-controls", "job-filters-panel");
    expect(disclosure.closest("details")).not.toHaveAttribute("open");
    await user.click(disclosure);
    expect(disclosure.closest("details")).toHaveAttribute("open");

    expect(screen.getByRole("searchbox", { name: "Recherche libre" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Lieux des offres" })).toBeVisible();
    expect(screen.getByRole("listbox", { name: "Contrats" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Télétravail des offres" })).toHaveValue(
      "false",
    );
    expect(screen.getByRole("listbox", { name: "Expérience" })).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "Salaire minimum" })).toHaveValue(0);
    expect(screen.getByRole("textbox", { name: "Entreprises" })).toBeVisible();
    expect(screen.getByRole("listbox", { name: "Sources" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Compétences" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Doublons" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Trier par" })).toHaveValue(
      "relevance",
    );
  });
});
