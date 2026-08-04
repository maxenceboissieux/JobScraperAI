export function JobGridSkeleton() {
  return (
    <section className="job-grid-skeleton" aria-label="Chargement des offres" aria-live="polite">
      {Array.from({ length: 6 }, (_, index) => (
        <div className="job-grid-skeleton__card" key={index} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      ))}
    </section>
  );
}
