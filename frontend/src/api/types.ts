export type SourceName =
  | "linkedin"
  | "hellowork"
  | "francetravail"
  | "wttj"
  | "freework"
  | "adzuna";

export type ContractType =
  | "cdi"
  | "cdd"
  | "interim"
  | "stage"
  | "alternance"
  | "freelance"
  | "other";

export type ExperienceLevel =
  | "internship"
  | "junior"
  | "mid"
  | "senior"
  | "lead"
  | "director";

export type WorkplaceType = "on_site" | "remote" | "hybrid";
export type SyncStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "partial"
  | "failed";

export type SearchCreate = {
  name: string;
  keywords: string[];
  title?: string | null;
  location?: string;
  radiusKm?: number | null;
  contractTypes?: ContractType[];
  experienceLevels?: ExperienceLevel[];
  workplaceTypes?: WorkplaceType[];
  companies?: string[];
  excludeCompanies?: string[];
  salaryMin?: number | null;
  sources: SourceName[];
  active?: boolean;
};

export type SearchUpdate = {
  name?: string;
  keywords?: string[];
  title?: string | null;
  location?: string;
  radiusKm?: number | null;
  contractTypes?: ContractType[];
  experienceLevels?: ExperienceLevel[];
  workplaceTypes?: WorkplaceType[];
  companies?: string[];
  excludeCompanies?: string[];
  salaryMin?: number | null;
  sources?: SourceName[];
  active?: boolean;
};

export type SavedSearch = {
  id: string;
  name: string;
  keywords: string[];
  title: string | null;
  location: string;
  radiusKm: number | null;
  contractTypes: string[];
  experienceLevels: string[];
  workplaceTypes: string[];
  companies: string[];
  excludeCompanies: string[];
  salaryMin: number | null;
  sources: string[];
  active: boolean;
  createdAt: string;
  updatedAt: string;
};

export type SourceLink = {
  source: string;
  url: string;
  active: boolean;
};

export type PossibleDuplicate = {
  id: string;
  title: string;
  company: string;
  location: string;
  score: number;
  reasons: string[];
};

export type DuplicateState = "confirmed" | "possible" | "none";

export type JobCard = {
  id: string;
  title: string;
  company: string;
  location: string;
  salaryMin: number | null;
  salaryMax: number | null;
  salaryCurrency: string;
  contractType: string | null;
  experienceLevel: string | null;
  remote: boolean | null;
  postedAt: string | null;
  sources: SourceLink[];
  duplicateState: DuplicateState;
  possibleDuplicates: PossibleDuplicate[];
};

export type JobDetails = JobCard & {
  description: string | null;
  skills: string[];
  benefits: string[];
  cacheState: "fresh" | "refreshed" | "stale";
  updatedAt: string;
  warning: string | null;
};

export type JobsPage = {
  items: JobCard[];
  total: number;
  limit: number;
  offset: number;
};

export type JobFilters = {
  savedSearchId?: string;
  period?: "24h" | "3d" | "7d" | "all";
  query?: string;
  locations?: string[];
  contracts?: string[];
  remote?: boolean;
  experience?: string[];
  salaryMin?: number;
  companies?: string[];
  sources?: string[];
  skills?: string[];
  duplicateState?: DuplicateState;
  sort?: "date" | "relevance";
  limit?: number;
  offset?: number;
};

export type StartSyncRequest = {
  savedSearchId: string;
  sources?: SourceName[] | null;
};

export type SourceProgress = {
  source: string;
  status: SyncStatus;
  offersSeen: number;
  offersPersisted: number;
  errorMessage: string | null;
  startedAt: string | null;
  finishedAt: string | null;
};

export type SyncRun = {
  id: string;
  savedSearchId: string;
  status: SyncStatus;
  requestedSources: string[];
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  sources: SourceProgress[];
};

export type GetSearchesOptions = {
  active?: boolean;
  signal?: AbortSignal;
};
