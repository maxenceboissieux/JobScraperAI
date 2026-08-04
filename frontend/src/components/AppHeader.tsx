import type { ReactNode } from "react";

type AppHeaderProps = {
  searchControls: ReactNode;
  syncStatus?: ReactNode;
  refreshAction?: ReactNode;
};

export function AppHeader({
  searchControls,
  syncStatus = (
    <p className="sync-summary">
      <span className="sync-summary__dot" aria-hidden="true" />
      Aucune synchronisation lancée
    </p>
  ),
  refreshAction = (
    <button
      type="button"
      className="button button--refresh"
      disabled
      title="L’actualisation sera disponible avec la synchronisation"
    >
      <span aria-hidden="true">↻</span>
      Actualiser
    </button>
  ),
}: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="app-header__topline">
        <div className="brand-lockup">
          <div className="brand-lockup__mark" aria-hidden="true">
            VE
          </div>
          <div>
            <p className="eyebrow">Agrégateur local</p>
            <h1>Veille Emploi</h1>
          </div>
        </div>

        <div className="app-header__sync" aria-label="État de la synchronisation">
          {syncStatus}
          {refreshAction}
        </div>
      </div>

      <div className="app-header__searches">{searchControls}</div>
    </header>
  );
}
