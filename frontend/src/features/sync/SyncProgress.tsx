import type { SourceProgress, SyncRun } from "../../api/types";

const SOURCE_LABELS: Record<string, string> = {
  freework: "Free-Work",
  linkedin: "LinkedIn",
  hellowork: "HelloWork",
  francetravail: "France Travail",
  wttj: "Welcome to the Jungle",
  adzuna: "Adzuna",
};

const SOURCE_STATUS_LABELS: Record<string, string> = {
  pending: "en attente",
  running: "en cours",
  succeeded: "terminée",
  failed: "échec",
  partial: "partielle",
};

const RUN_STATUS_LABELS: Record<string, string> = {
  pending: "Synchronisation en attente",
  running: "Synchronisation en cours",
  succeeded: "Synchronisation terminée",
  partial: "Synchronisation partielle",
  failed: "Échec de la synchronisation",
};

type SyncProgressProps = {
  run: SyncRun | null | undefined;
  errorMessage: string | null;
  isRetrying: boolean;
  onRetrySource: (source: string) => void;
  onRetryLatest: () => void;
};

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

function sourceStatusLabel(status: SourceProgress["status"]): string {
  return SOURCE_STATUS_LABELS[status] ?? status;
}

export function SyncProgress({
  run,
  errorMessage,
  isRetrying,
  onRetrySource,
  onRetryLatest,
}: SyncProgressProps) {
  if (run === null || run === undefined) {
    return (
      <div className="sync-progress">
        <p className="sync-summary">
          <span className="sync-summary__dot" aria-hidden="true" />
          Aucune synchronisation lancée
        </p>
        {errorMessage ? (
          <p className="sync-error" role="alert">
            {errorMessage}
            <button type="button" className="button button--quiet" onClick={onRetryLatest}>
              Réessayer
            </button>
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="sync-progress">
      <p className={`sync-summary sync-summary--${run.status}`} aria-live="polite">
        <span className="sync-summary__dot" aria-hidden="true" />
        {RUN_STATUS_LABELS[run.status] ?? run.status}
      </p>
      <ul className="sync-progress__sources" aria-label="Progression des sources">
        {run.sources.map((source) => {
          const label = sourceLabel(source.source);
          return (
            <li key={source.source}>
              <span>
                {label} : {sourceStatusLabel(source.status)}
              </span>
              {source.status === "failed" ? (
                <button
                  type="button"
                  className="button button--quiet"
                  disabled={isRetrying}
                  onClick={() => onRetrySource(source.source)}
                >
                  Relancer {label}
                </button>
              ) : null}
              {source.errorMessage ? <small>{source.errorMessage}</small> : null}
            </li>
          );
        })}
      </ul>
      {errorMessage ? (
        <p className="sync-error" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
