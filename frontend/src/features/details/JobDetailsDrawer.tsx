import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "../../api/client";
import type { JobDetails } from "../../api/types";
import {
  formatContractType,
  formatExperienceLevel,
  formatFrenchDate,
  formatSalary,
  formatWorkplace,
} from "../../formatters";
import { JobDescription } from "./JobDescription";
import { PossibleDuplicates } from "./PossibleDuplicates";
import { SourceLinks } from "./SourceLinks";

type JobDetailsDrawerProps = {
  jobId: string;
  onClose: () => void;
  onSelectJob: (jobId: string) => void;
};

function updatedAtLabel(updatedAt: string): string | null {
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return "Détails mis à jour aujourd’hui";
  }
  return `Détails mis à jour le ${new Intl.DateTimeFormat("fr-FR").format(date)}`;
}

function DetailChips({
  id,
  title,
  values,
}: {
  id: string;
  title: string;
  values: string[];
}) {
  const visibleValues = values.filter((value) => value.trim());
  if (visibleValues.length === 0) {
    return null;
  }
  return (
    <section className="job-drawer__chip-section" aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      <ul className="job-drawer__chips">
        {visibleValues.map((value, index) => (
          <li key={`${value}:${index}`}>{value}</li>
        ))}
      </ul>
    </section>
  );
}

function JobMetadata({ job }: { job: JobDetails }) {
  const items = [
    { label: "Entreprise", value: job.company.trim() || null },
    { label: "Lieu", value: job.location.trim() || null },
    { label: "Contrat", value: formatContractType(job.contractType) },
    { label: "Expérience", value: formatExperienceLevel(job.experienceLevel) },
    { label: "Organisation", value: formatWorkplace(job.remote) },
    { label: "Salaire", value: formatSalary(job) },
    { label: "Publication", value: formatFrenchDate(job.postedAt) },
  ].filter((item): item is { label: string; value: string } => item.value !== null);

  if (items.length === 0) {
    return null;
  }
  return (
    <dl
      className="job-drawer__metadata"
      role="group"
      aria-label="Informations sur l’offre"
    >
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>{" "}
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function JobDetailsDrawer({ jobId, onClose, onSelectJob }: JobDetailsDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const detailsQuery = useQuery({
    queryKey: ["job-details", jobId],
    queryFn: ({ signal }) => api.getJob(jobId, signal),
  });
  const updateLabel = detailsQuery.data
    ? updatedAtLabel(detailsQuery.data.updatedAt)
    : null;

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const focusable = Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => !element.hidden);
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!panelRef.current?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  return (
    <div className="job-drawer" role="dialog" aria-modal="true" aria-labelledby="job-drawer-title">
      <div className="job-drawer__panel" ref={panelRef}>
        <header className="job-drawer__header">
          <p className="eyebrow" id="job-drawer-title">
            Détails de l’offre
          </p>
          <button
            type="button"
            ref={closeButtonRef}
            onClick={onClose}
            aria-label="Fermer les détails"
            className="job-drawer__close"
          >
            ×
          </button>
        </header>
        {detailsQuery.isPending ? (
          <div className="job-drawer__skeleton" role="status" aria-live="polite">
            <span className="visually-hidden">Chargement des détails…</span>
            <span aria-hidden="true" />
            <span aria-hidden="true" />
            <span aria-hidden="true" />
          </div>
        ) : null}
        {detailsQuery.isError ? (
          <section className="job-drawer__error" role="alert">
            <h2>Impossible de charger les détails.</h2>
            <p>Vérifiez que le service local est démarré, puis réessayez.</p>
            <button
              type="button"
              className="button button--primary"
              onClick={() => void detailsQuery.refetch()}
            >
              Réessayer
            </button>
          </section>
        ) : null}
        {detailsQuery.data ? (
          <div className="job-drawer__content">
            {detailsQuery.data.cacheState === "stale" &&
            detailsQuery.data.warning?.trim() ? (
              <p className="job-drawer__warning" role="status">
                {detailsQuery.data.warning}
              </p>
            ) : null}
            <h2>{detailsQuery.data.title}</h2>
            {updateLabel ? (
              <p className="job-drawer__updated-at">{updateLabel}</p>
            ) : null}
            <JobMetadata job={detailsQuery.data} />
            {detailsQuery.data.description?.trim() ? (
              <JobDescription description={detailsQuery.data.description} />
            ) : null}
            <DetailChips
              id="job-skills-title"
              title="Compétences"
              values={detailsQuery.data.skills}
            />
            <DetailChips
              id="job-benefits-title"
              title="Avantages"
              values={detailsQuery.data.benefits}
            />
            <SourceLinks sources={detailsQuery.data.sources} />
            <PossibleDuplicates
              duplicates={detailsQuery.data.possibleDuplicates}
              onSelect={onSelectJob}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
