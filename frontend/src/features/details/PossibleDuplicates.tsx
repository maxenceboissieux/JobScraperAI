import type { PossibleDuplicate } from "../../api/types";

type PossibleDuplicatesProps = {
  duplicates: PossibleDuplicate[];
  onSelect: (jobId: string) => void;
};

export function PossibleDuplicates({
  duplicates,
  onSelect,
}: PossibleDuplicatesProps) {
  if (duplicates.length === 0) {
    return null;
  }

  return (
    <section
      className="job-drawer__duplicates"
      aria-labelledby="possible-duplicates-title"
    >
      <h3 id="possible-duplicates-title">Offres similaires possibles</h3>
      <div className="job-drawer__duplicate-list">
        {duplicates.map((duplicate) => (
          <button
            type="button"
            className="job-drawer__duplicate"
            key={duplicate.id}
            onClick={() => onSelect(duplicate.id)}
            aria-label={`Voir l’offre similaire ${duplicate.title}`}
          >
            <strong>{duplicate.title}</strong>
            {[duplicate.company, duplicate.location]
              .filter((value) => value.trim())
              .join(" · ") ? (
              <span>
                {[duplicate.company, duplicate.location]
                  .filter((value) => value.trim())
                  .join(" · ")}
              </span>
            ) : null}
          </button>
        ))}
      </div>
    </section>
  );
}
