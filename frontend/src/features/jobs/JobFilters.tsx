import { useEffect, useId, useState, type KeyboardEvent } from "react";

import type { JobFilters as ApiJobFilters } from "../../api/types";
import type { JobFilterValues } from "./useJobFilters";

type SetFilter = <K extends keyof JobFilterValues>(
  key: K,
  value: JobFilterValues[K],
) => void;

type JobFiltersProps = {
  filters: ApiJobFilters;
  activeCount: number;
  queryDraft: string;
  setQueryDraft: (value: string) => void;
  setFilter: SetFilter;
  clearFilters: () => void;
};

const CONTRACTS = [
  ["cdi", "CDI"],
  ["cdd", "CDD"],
  ["interim", "Intérim"],
  ["stage", "Stage"],
  ["alternance", "Alternance"],
  ["freelance", "Freelance"],
  ["other", "Autre"],
] as const;
const EXPERIENCES = [
  ["internship", "Début de carrière"],
  ["junior", "Junior"],
  ["mid", "Intermédiaire"],
  ["senior", "Senior"],
  ["lead", "Lead"],
  ["director", "Direction"],
] as const;
const SOURCES = [
  ["freework", "Free-Work"],
  ["linkedin", "LinkedIn"],
  ["hellowork", "HelloWork"],
  ["francetravail", "France Travail"],
  ["wttj", "Welcome to the Jungle"],
  ["adzuna", "Adzuna"],
] as const;

function selectedValues(element: HTMLSelectElement): string[] | undefined {
  const values = Array.from(element.selectedOptions, (option) => option.value);
  return values.length > 0 ? values : undefined;
}

function useDesktopFilters() {
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window.matchMedia === "function"
      ? window.matchMedia("(min-width: 768px)").matches
      : false,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(min-width: 768px)");
    const update = (event: MediaQueryListEvent) => setIsDesktop(event.matches);
    setIsDesktop(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return isDesktop;
}

function TagFilter({
  id,
  label,
  inputLabel,
  itemName,
  values,
  placeholder,
  onCommit,
}: {
  id: string;
  label: string;
  inputLabel: string;
  itemName: string;
  values: string[] | undefined;
  placeholder: string;
  onCommit: (values: string[] | undefined) => void;
}) {
  const [draft, setDraft] = useState("");

  useEffect(() => setDraft(""), [values]);

  function addDraft() {
    const value = draft.trim();
    if (!value) return;
    if (!values?.includes(value)) onCommit([...(values ?? []), value]);
    setDraft("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      addDraft();
    } else if (event.key === "Backspace" && draft === "" && values?.length) {
      onCommit(values.length === 1 ? undefined : values.slice(0, -1));
    }
  }

  return (
    <div className="job-filter-field">
      <span className="job-filter-label">{label}</span>
      {values?.length ? (
        <div className="job-filter-tags" aria-label={`${label} sélectionnés`}>
          {values.map((value) => (
            <button
              key={value}
              type="button"
              className="job-filter-tag"
              aria-label={`Supprimer ${itemName} ${value}`}
              onClick={() => {
                const next = values.filter((candidate) => candidate !== value);
                onCommit(next.length > 0 ? next : undefined);
              }}
            >
              <span>{value}</span>
              <span aria-hidden="true">×</span>
            </button>
          ))}
        </div>
      ) : null}
      <label className="visually-hidden" htmlFor={id}>
        {inputLabel}
      </label>
      <input
        id={id}
        value={draft}
        placeholder={placeholder}
        onBlur={addDraft}
        onChange={(event) => setDraft(event.currentTarget.value)}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
}

export function JobFilters({
  filters,
  activeCount,
  queryDraft,
  setQueryDraft,
  setFilter,
  clearFilters,
}: JobFiltersProps) {
  const isDesktop = useDesktopFilters();
  const [mobileOpen, setMobileOpen] = useState(false);
  const salaryErrorId = useId();
  const [salaryDraft, setSalaryDraft] = useState(
    filters.salaryMin === undefined ? "" : String(filters.salaryMin),
  );
  const salaryIsValid = salaryDraft === "" || /^\d+(?:\.\d+)?$/.test(salaryDraft);

  useEffect(() => {
    setSalaryDraft(filters.salaryMin === undefined ? "" : String(filters.salaryMin));
  }, [filters.salaryMin]);

  function commitSalary() {
    if (!salaryIsValid) return;
    setFilter("salaryMin", salaryDraft === "" ? undefined : Number(salaryDraft));
  }

  const activeLabel = `${activeCount} ${activeCount > 1 ? "actifs" : "actif"}`;
  const disclosureOpen = isDesktop || mobileOpen;

  return (
    <details
      className="filter-disclosure"
      open={disclosureOpen}
      onToggle={(event) => {
        if (!isDesktop && event.currentTarget.open !== mobileOpen) {
          setMobileOpen(event.currentTarget.open);
        }
      }}
    >
      <summary
        role="button"
        className="filter-disclosure__summary"
        aria-controls="job-filters-panel"
        aria-label={`${disclosureOpen ? "Masquer" : "Afficher"} les filtres, ${activeLabel}`}
      >
        <span>Filtres</span>
        <span className="filter-count">{activeLabel}</span>
      </summary>

      <div className="job-filter-panel" id="job-filters-panel">
        <div className="job-filter-field job-filter-field--query">
          <label htmlFor="job-query">Recherche libre</label>
          <input
            id="job-query"
            type="search"
            value={queryDraft}
            placeholder="Titre, entreprise, mot-clé…"
            onChange={(event) => setQueryDraft(event.currentTarget.value)}
          />
        </div>

        <TagFilter
          id="job-locations"
          label="Lieux des offres"
          inputLabel="Ajouter un lieu"
          itemName="le lieu"
          values={filters.locations}
          placeholder="Ajouter puis Entrée"
          onCommit={(values) => setFilter("locations", values)}
        />

        <div className="job-filter-field">
          <label htmlFor="job-contracts">Contrats</label>
          <select
            id="job-contracts"
            multiple
            size={3}
            value={filters.contracts ?? []}
            onChange={(event) =>
              setFilter("contracts", selectedValues(event.currentTarget))
            }
          >
            {CONTRACTS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>

        <div className="job-filter-field">
          <label htmlFor="job-remote">Télétravail des offres</label>
          <select
            id="job-remote"
            value={filters.remote === undefined ? "" : String(filters.remote)}
            onChange={(event) =>
              setFilter(
                "remote",
                event.currentTarget.value === ""
                  ? undefined
                  : event.currentTarget.value === "true",
              )
            }
          >
            <option value="">Indifférent</option>
            <option value="true">Oui</option>
            <option value="false">Non</option>
          </select>
        </div>

        <div className="job-filter-field">
          <label htmlFor="job-experience">Expérience</label>
          <select
            id="job-experience"
            multiple
            size={3}
            value={filters.experience ?? []}
            onChange={(event) =>
              setFilter("experience", selectedValues(event.currentTarget))
            }
          >
            {EXPERIENCES.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>

        <div className="job-filter-field">
          <label htmlFor="job-salary">Salaire minimum</label>
          <input
            id="job-salary"
            type="number"
            min="0"
            step="1"
            inputMode="numeric"
            value={salaryDraft}
            aria-invalid={!salaryIsValid}
            aria-describedby={!salaryIsValid ? salaryErrorId : undefined}
            placeholder="Sans minimum"
            onBlur={commitSalary}
            onChange={(event) => setSalaryDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitSalary();
              }
            }}
          />
          {!salaryIsValid ? (
            <p className="field-error" id={salaryErrorId} role="alert">
              Saisissez un salaire positif ou nul.
            </p>
          ) : null}
        </div>

        <TagFilter
          id="job-companies"
          label="Entreprises"
          inputLabel="Ajouter une entreprise"
          itemName="l’entreprise"
          values={filters.companies}
          placeholder="Ajouter puis Entrée"
          onCommit={(values) => setFilter("companies", values)}
        />

        <div className="job-filter-field">
          <label htmlFor="job-sources">Sources</label>
          <select
            id="job-sources"
            multiple
            size={3}
            value={filters.sources ?? []}
            onChange={(event) =>
              setFilter("sources", selectedValues(event.currentTarget))
            }
          >
            {SOURCES.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>

        <TagFilter
          id="job-skills"
          label="Compétences"
          inputLabel="Ajouter une compétence"
          itemName="la compétence"
          values={filters.skills}
          placeholder="Ajouter puis Entrée"
          onCommit={(values) => setFilter("skills", values)}
        />

        <div className="job-filter-field">
          <label htmlFor="job-duplicates">Doublons</label>
          <select
            id="job-duplicates"
            value={filters.duplicateState ?? ""}
            onChange={(event) =>
              setFilter(
                "duplicateState",
                (event.currentTarget.value || undefined) as JobFilterValues["duplicateState"],
              )
            }
          >
            <option value="">Tous</option>
            <option value="possible">Doublons possibles</option>
            <option value="confirmed">Regroupés</option>
            <option value="none">Sans doublon</option>
          </select>
        </div>

        <div className="job-filter-field">
          <label htmlFor="job-sort">Trier par</label>
          <select
            id="job-sort"
            value={filters.sort ?? "date"}
            onChange={(event) =>
              setFilter("sort", event.currentTarget.value as JobFilterValues["sort"])
            }
          >
            <option value="date">Date</option>
            <option value="relevance">Pertinence</option>
          </select>
        </div>

        <div className="job-filter-actions">
          <button type="button" className="button button--quiet" onClick={clearFilters}>
            Effacer les filtres
          </button>
        </div>
      </div>
    </details>
  );
}
