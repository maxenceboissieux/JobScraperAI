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

function TextListFilter({
  id,
  label,
  values,
  placeholder,
  onCommit,
}: {
  id: string;
  label: string;
  values: string[] | undefined;
  placeholder: string;
  onCommit: (values: string[] | undefined) => void;
}) {
  const serialized = values?.join(", ") ?? "";
  const [draft, setDraft] = useState(serialized);

  useEffect(() => setDraft(serialized), [serialized]);

  function commit() {
    const seen = new Set<string>();
    const parsed = draft
      .split(",")
      .map((value) => value.trim())
      .filter((value) => {
        if (!value || seen.has(value)) return false;
        seen.add(value);
        return true;
      });
    onCommit(parsed.length > 0 ? parsed : undefined);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    }
  }

  return (
    <div className="job-filter-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        value={draft}
        placeholder={placeholder}
        onBlur={commit}
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

  return (
    <details className="filter-disclosure">
      <summary
        role="button"
        className="filter-disclosure__summary"
        aria-controls="job-filters-panel"
        aria-label={`Afficher les filtres, ${activeLabel}`}
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

        <TextListFilter
          id="job-locations"
          label="Lieux des offres"
          values={filters.locations}
          placeholder="Paris, Lyon"
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

        <TextListFilter
          id="job-companies"
          label="Entreprises"
          values={filters.companies}
          placeholder="Acme, Exemple"
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

        <TextListFilter
          id="job-skills"
          label="Compétences"
          values={filters.skills}
          placeholder="Python, React"
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
