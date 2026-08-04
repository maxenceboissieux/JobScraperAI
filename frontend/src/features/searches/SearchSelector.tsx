import type { SavedSearch } from "../../api/types";

type SearchSelectorProps = {
  searches: SavedSearch[];
  selectedId: string | null;
  isLoading: boolean;
  isBusy: boolean;
  onSelect: (searchId: string) => void;
  onCreate: () => void;
  onEdit: () => void;
  onToggleActive: () => void;
};

export function SearchSelector({
  searches,
  selectedId,
  isLoading,
  isBusy,
  onSelect,
  onCreate,
  onEdit,
  onToggleActive,
}: SearchSelectorProps) {
  const selected = searches.find((search) => search.id === selectedId) ?? null;
  const hasSearches = searches.length > 0;

  return (
    <section className="search-selector" aria-label="Gestion des recherches">
      <div className="search-selector__field">
        <label htmlFor="saved-search">Recherche enregistrée</label>
        <div className="select-shell">
          <select
            id="saved-search"
            value={selected?.id ?? ""}
            disabled={isLoading || isBusy || !hasSearches}
            onChange={(event) => onSelect(event.currentTarget.value)}
          >
            {isLoading ? <option value="">Chargement…</option> : null}
            {!isLoading && !hasSearches ? (
              <option value="">Aucune recherche</option>
            ) : null}
            {searches.map((search) => (
              <option key={search.id} value={search.id}>
                {search.name}
                {search.active ? "" : " (suspendue)"}
              </option>
            ))}
          </select>
          <span className="select-shell__icon" aria-hidden="true">
            ↓
          </span>
        </div>
      </div>

      <div className="search-selector__actions">
        <button
          type="button"
          className="button button--primary"
          onClick={onCreate}
          disabled={isBusy}
        >
          <span aria-hidden="true">＋</span>
          Nouvelle recherche
        </button>
        <button
          type="button"
          className="button button--quiet"
          onClick={onEdit}
          disabled={isBusy || selected === null}
        >
          Modifier la recherche
        </button>
        <button
          type="button"
          className="button button--quiet"
          onClick={onToggleActive}
          disabled={isBusy || selected === null}
        >
          {selected === null || selected.active
            ? "Suspendre la recherche"
            : "Réactiver la recherche"}
        </button>
      </div>
    </section>
  );
}
