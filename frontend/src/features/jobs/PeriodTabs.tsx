import type { JobFilters } from "../../api/types";

const PERIODS: readonly { value: JobFilters["period"]; label: string }[] = [
  { value: "24h", label: "24 h" },
  { value: "3d", label: "3 jours" },
  { value: "7d", label: "7 jours" },
  { value: "all", label: "Toutes" },
];

type PeriodTabsProps = {
  period: JobFilters["period"];
  onChange: (period: JobFilters["period"]) => void;
};

export function PeriodTabs({ period, onChange }: PeriodTabsProps) {
  return (
    <nav className="period-tabs" aria-label="Période de publication">
      {PERIODS.map((choice) => {
        const selected = choice.value === period;
        return (
          <button
            key={choice.value}
            type="button"
            className="period-tabs__button"
            aria-pressed={selected}
            aria-current={selected ? "true" : undefined}
            onClick={() => onChange(choice.value)}
          >
            {choice.label}
          </button>
        );
      })}
    </nav>
  );
}
