import type { SourceLink } from "../../api/types";

type SourceLinksProps = {
  sources: SourceLink[];
};

export function SourceLinks({ sources }: SourceLinksProps) {
  if (sources.length === 0) {
    return null;
  }

  return (
    <section className="job-drawer__sources" aria-labelledby="job-sources-title">
      <h3 id="job-sources-title">Sources</h3>
      <div className="job-drawer__source-links">
        {sources.map((source) => (
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            key={`${source.source}:${source.url}`}
          >
            {source.source}
            <span aria-hidden="true"> ↗</span>
          </a>
        ))}
      </div>
    </section>
  );
}
