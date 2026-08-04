import type { JobCard as JobCardDto } from "../../api/types";

type JobCardProps = {
  job: JobCardDto;
  onSelect: (jobId: string) => void;
};

function formatRelativeDate(postedAt: string | null): string | null {
  if (postedAt === null) {
    return null;
  }
  const date = new Date(postedAt);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  const difference = Math.max(0, Date.now() - date.getTime());
  const days = Math.floor(difference / 86_400_000);
  if (days === 0) return "Aujourd’hui";
  if (days === 1) return "Il y a 1 jour";
  return `Il y a ${days} jours`;
}

function formatSalary(job: JobCardDto): string | null {
  if (
    (job.salaryMin === null && job.salaryMax === null) ||
    !/^[A-Za-z]{3}$/.test(job.salaryCurrency)
  ) {
    return null;
  }
  const formatter = new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: job.salaryCurrency.toUpperCase(),
    maximumFractionDigits: 0,
  });
  if (job.salaryMin !== null && job.salaryMax !== null) {
    return `${formatter.format(job.salaryMin)} – ${formatter.format(job.salaryMax)}`;
  }
  if (job.salaryMin !== null) return `À partir de ${formatter.format(job.salaryMin)}`;
  if (job.salaryMax !== null) return `Jusqu’à ${formatter.format(job.salaryMax)}`;
  return null;
}

export function JobCard({ job, onSelect }: JobCardProps) {
  const relativeDate = formatRelativeDate(job.postedAt);
  const salary = formatSalary(job);
  const metadata = [
    job.company.trim() || null,
    job.location.trim() || null,
    job.contractType,
    relativeDate,
    job.remote === true ? "Télétravail" : job.remote === false ? "Sur site" : null,
  ].filter((value): value is string => value !== null && value !== "");

  return (
    <article className="job-card">
      <button
        type="button"
        className="job-card__button"
        onClick={() => onSelect(job.id)}
        aria-label={`Voir l’offre ${job.title}`}
      >
        <h2>{job.title}</h2>
        {metadata.length > 0 ? (
          <p className="job-card__metadata">{metadata.join(" · ")}</p>
        ) : null}
        {salary !== null ? <p className="job-card__salary">{salary}</p> : null}
        <div className="job-card__badges">
          {job.sources.map((source) =>
            source.source.trim() ? (
              <span className="job-card__source" key={`${source.source}:${source.url}`}>
                {source.source}
              </span>
            ) : null,
          )}
          {job.duplicateState === "possible" ? (
            <span className="job-card__duplicate">Doublon possible</span>
          ) : null}
        </div>
      </button>
    </article>
  );
}
