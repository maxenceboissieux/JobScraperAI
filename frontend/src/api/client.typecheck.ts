import { api } from "./client";
import type { JobFilters } from "./types";

if (false) {
  // @ts-expect-error getJobs always requires explicit local-query semantics.
  void api.getJobs();

  // @ts-expect-error period must never silently fall back to backend "all".
  void api.getJobs({ limit: 24, offset: 0 });

  // @ts-expect-error pagination limit is required by the frontend contract.
  void api.getJobs({ period: "3d", offset: 0 });

  // @ts-expect-error pagination offset is required by the frontend contract.
  void api.getJobs({ period: "3d", limit: 24 });

  const filters: JobFilters = { period: "3d", limit: 24, offset: 0 };
  void api.getJobs(filters);
}
