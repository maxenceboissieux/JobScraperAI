import type { JobCard } from "./api/types";

const SOURCE_LABELS: Record<string, string> = {
  freework: "Free-Work",
  "free-work": "Free-Work",
  linkedin: "LinkedIn",
  hellowork: "HelloWork",
  francetravail: "France Travail",
  "france travail": "France Travail",
  wttj: "Welcome to the Jungle",
  "welcome to the jungle": "Welcome to the Jungle",
  adzuna: "Adzuna",
};

const CONTRACT_LABELS: Record<string, string> = {
  cdi: "CDI",
  cdd: "CDD",
  interim: "Intérim",
  stage: "Stage",
  alternance: "Alternance",
  freelance: "Freelance",
  other: "Autre",
};

const EXPERIENCE_LABELS: Record<string, string> = {
  internship: "Début de carrière",
  junior: "Junior",
  mid: "Intermédiaire",
  senior: "Senior",
  lead: "Lead",
  director: "Direction",
};

const WORKPLACE_LABELS: Record<string, string> = {
  on_site: "Sur site",
  remote: "Télétravail",
  hybrid: "Hybride",
};

function mappedLabel(value: string | null, labels: Record<string, string>): string | null {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) {
    return null;
  }
  return labels[trimmed.toLocaleLowerCase("fr-FR")] ?? trimmed;
}

export function formatSourceName(source: string): string {
  return mappedLabel(source, SOURCE_LABELS) ?? "";
}

export function formatContractType(contractType: string | null): string | null {
  return mappedLabel(contractType, CONTRACT_LABELS);
}

export function formatExperienceLevel(
  experienceLevel: string | null,
): string | null {
  return mappedLabel(experienceLevel, EXPERIENCE_LABELS);
}

export function formatWorkplace(
  workplace: string | boolean | null,
): string | null {
  if (typeof workplace === "boolean") {
    return workplace ? WORKPLACE_LABELS.remote : WORKPLACE_LABELS.on_site;
  }
  return mappedLabel(workplace, WORKPLACE_LABELS);
}

export function formatSalary(
  job: Pick<JobCard, "salaryMin" | "salaryMax" | "salaryCurrency">,
): string | null {
  if (
    (job.salaryMin === null && job.salaryMax === null) ||
    !/^[A-Za-z]{3}$/.test(job.salaryCurrency)
  ) {
    return null;
  }
  const formatter = new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: job.salaryCurrency.toUpperCase(),
    maximumFractionDigits: 0,
  });
  if (job.salaryMin !== null && job.salaryMax !== null) {
    return `${formatter.format(job.salaryMin)} – ${formatter.format(job.salaryMax)}`;
  }
  if (job.salaryMin !== null) return `À partir de ${formatter.format(job.salaryMin)}`;
  if (job.salaryMax !== null) return `Jusqu’à ${formatter.format(job.salaryMax)}`;
  return null;
}

export function formatRelativeDate(postedAt: string | null): string | null {
  if (postedAt === null) {
    return null;
  }
  const date = new Date(postedAt);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  const difference = Math.max(0, Date.now() - date.getTime());
  const days = Math.floor(difference / 86_400_000);
  if (days === 0) return "Aujourd’hui";
  if (days === 1) return "Il y a 1 jour";
  return `Il y a ${days} jours`;
}

export function formatFrenchDate(value: string | null): string | null {
  if (value === null) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "long",
    timeZone: "Europe/Paris",
  }).format(date);
}

export function formatFrenchDateTime(value: string | null): string | null {
  if (value === null) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "Europe/Paris",
  }).format(date);
}
