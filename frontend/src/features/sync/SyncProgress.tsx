import type { SourceProgress, SyncRun } from "../../api/types";
import { formatFrenchDateTime, formatSourceName } from "../../formatters";

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

function sourceStatusLabel(status: SourceProgress["status"]): string {
  return SOURCE_STATUS_LABELS[status] ?? status;
}

function sourceCountsLabel(source: SourceProgress): string {
  const seenLabel = source.offersSeen === 1 ? "offre vue" : "offres vues";
  const persistedLabel =
    source.offersPersisted === 1 ? "offre enregistrée" : "offres enregistrées";
  return `${source.offersSeen} ${seenLabel} · ${source.offersPersisted} ${persistedLabel}`;
}

function sourceFinishedLabel(finishedAt: string | null): string | null {
  if (finishedAt === null) {
    return null;
  }
  const formatted = formatFrenchDateTime(finishedAt);
  return formatted === null ? null : `Terminée le ${formatted}`;
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
          const label = formatSourceName(source.source);
          const finishedLabel = sourceFinishedLabel(source.finishedAt);
          return (
            <li key={source.source}>
              <span>
                {label} : {sourceStatusLabel(source.status)}
              </span>
              <small className="sync-progress__metadata">
                {sourceCountsLabel(source)}
              </small>
              {finishedLabel ? (
                <small className="sync-progress__metadata">
                  <time dateTime={source.finishedAt ?? undefined}>{finishedLabel}</time>
                </small>
              ) : null}
              {source.status === "failed" || source.status === "partial" ? (
                <button
                  type="button"
                  className="button button--quiet"
                  disabled={isRetrying}
                  onClick={() => onRetrySource(source.source)}
                >
                  Relancer {label}
                </button>
              ) : null}
              {source.errorMessage ? (
                <small className="sync-progress__error">{source.errorMessage}</small>
              ) : null}
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
