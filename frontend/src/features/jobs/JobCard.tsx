import type { JobCard as JobCardDto } from "../../api/types";
import {
  formatContractType,
  formatExperienceLevel,
  formatRelativeDate,
  formatSalary,
  formatSourceName,
  formatWorkplace,
} from "../../formatters";

type JobCardProps = {
  job: JobCardDto;
  onSelect: (jobId: string) => void;
};

export function JobCard({ job, onSelect }: JobCardProps) {
  const relativeDate = formatRelativeDate(job.postedAt);
  const salary = formatSalary(job);
  const metadata = [
    job.company.trim() || null,
    job.location.trim() || null,
    formatContractType(job.contractType),
    formatExperienceLevel(job.experienceLevel),
    relativeDate,
    formatWorkplace(job.remote),
  ].filter((value): value is string => value !== null && value !== "");

  return (
    <article className={`job-card${job.viewedAt ? " job-card--viewed" : ""}`}>
      <button
        type="button"
        className="job-card__button"
        onClick={() => onSelect(job.id)}
        aria-label={`Voir l’offre ${job.title}${job.viewedAt ? ", déjà vue" : ""}`}
      >
        {job.viewedAt ? (
          <span className="job-card__viewed-label">✓ Déjà vue</span>
        ) : null}
        <h2>{job.title}</h2>
        {metadata.length > 0 ? (
          <p className="job-card__metadata">{metadata.join(" · ")}</p>
        ) : null}
        {salary !== null ? <p className="job-card__salary">{salary}</p> : null}
        <div className="job-card__badges">
          {job.sources.map((source) => {
            const sourceName = formatSourceName(source.source);
            return sourceName ? (
              <span className="job-card__source" key={`${source.source}:${source.url}`}>
                {sourceName}
              </span>
            ) : null;
          })}
          {job.duplicateState === "possible" ? (
            <span className="job-card__duplicate">Doublon possible</span>
          ) : null}
        </div>
      </button>
    </article>
  );
}
