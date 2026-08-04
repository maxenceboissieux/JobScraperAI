type RefreshButtonProps = {
  hasSelectedSearch: boolean;
  isStarting: boolean;
  onRefresh: () => void;
};

export function RefreshButton({
  hasSelectedSearch,
  isStarting,
  onRefresh,
}: RefreshButtonProps) {
  const disabled = !hasSelectedSearch || isStarting;
  const title = !hasSelectedSearch
    ? "Sélectionnez une recherche avant d’actualiser."
    : isStarting
      ? "L’actualisation est en cours de lancement."
      : undefined;

  return (
    <button
      type="button"
      className="button button--refresh"
      disabled={disabled}
      title={title}
      onClick={onRefresh}
    >
      <span aria-hidden="true">↻</span>
      Actualiser
    </button>
  );
}
