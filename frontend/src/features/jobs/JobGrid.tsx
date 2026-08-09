import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { JobFilters } from "../../api/types";
import { JobCard } from "./JobCard";
import { JobGridSkeleton } from "./JobGridSkeleton";
import { useMarkJobViewed } from "./useMarkJobViewed";

type JobGridProps = {
  filters: JobFilters;
  onPageChange: (offset: number) => void;
  onSelectJob: (jobId: string) => void;
};

export function JobGrid({ filters, onPageChange, onSelectJob }: JobGridProps) {
  const { markViewed, errorMessage } = useMarkJobViewed();
  const jobsQuery = useQuery({
    queryKey: ["jobs", filters],
    queryFn: ({ signal }) => api.getJobs(filters, signal),
  });
  const selectFromCard = (jobId: string) => {
    onSelectJob(jobId);
    markViewed(jobId);
  };

  if (jobsQuery.isPending) {
    return <JobGridSkeleton />;
  }

  if (jobsQuery.isError && jobsQuery.data === undefined) {
    return (
      <section className="job-grid-state job-grid-state--error" role="alert">
        <h2>Impossible de charger les offres.</h2>
        <p>Vérifiez que le service local est démarré, puis réessayez.</p>
        <button
          type="button"
          className="button button--primary"
          onClick={() => void jobsQuery.refetch()}
        >
          Réessayer
        </button>
      </section>
    );
  }

  const page = jobsQuery.data;
  if (page.items.length === 0) {
    return (
      <section className="job-grid-state job-grid-state--empty">
        {errorMessage ? (
          <p className="status-banner status-banner--error" role="alert">
            {errorMessage}
          </p>
        ) : null}
        <h2>Aucune offre ne correspond à ces filtres</h2>
        <p>Modifiez vos filtres ou élargissez la période de publication.</p>
      </section>
    );
  }

  const hasPreviousPage = page.offset > 0;
  const hasNextPage = page.offset + page.items.length < page.total;

  return (
    <section className="job-results" aria-label="Offres d’emploi">
      {errorMessage ? (
        <p className="status-banner status-banner--error" role="alert">
          {errorMessage}
        </p>
      ) : null}
      <p className="job-results__count" aria-live="polite">
        {page.total} offre{page.total > 1 ? "s" : ""}
      </p>
      <div className="job-grid">
        {page.items.map((job) => (
          <JobCard job={job} key={job.id} onSelect={selectFromCard} />
        ))}
      </div>
      {hasPreviousPage || hasNextPage ? (
        <nav className="job-pagination" aria-label="Pagination des offres">
          <button
            type="button"
            className="button button--quiet"
            disabled={!hasPreviousPage}
            onClick={() => onPageChange(Math.max(0, page.offset - page.limit))}
          >
            Page précédente
          </button>
          <span>
            Page {Math.floor(page.offset / page.limit) + 1}
          </span>
          <button
            type="button"
            className="button button--quiet"
            disabled={!hasNextPage}
            onClick={() => onPageChange(page.offset + page.limit)}
          >
            Page suivante
          </button>
        </nav>
      ) : null}
    </section>
  );
}
