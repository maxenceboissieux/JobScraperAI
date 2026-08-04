import type {
  GetSearchesOptions,
  JobDetails,
  JobFilters,
  JobsPage,
  SavedSearch,
  SearchCreate,
  SearchUpdate,
  SourceName,
  StartSyncRequest,
  SyncRun,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, options?: ErrorOptions) {
    super(errorMessage(detail, status), options);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const first = detail[0];
    if (
      typeof first === "object" &&
      first !== null &&
      "msg" in first &&
      typeof first.msg === "string"
    ) {
      return first.msg;
    }
  }
  return status === 0
    ? "Impossible de joindre le serveur."
    : `Erreur HTTP ${status}.`;
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

function apiUrl(path: string): URL {
  const origin =
    typeof window === "undefined" ? "http://localhost:3000" : window.location.origin;
  return new URL(path, origin);
}

async function errorDetail(response: Response): Promise<unknown> {
  const text = await response.text();
  if (response.headers.get("content-type")?.includes("application/json")) {
    try {
      const body: unknown = JSON.parse(text);
      if (typeof body === "object" && body !== null && "detail" in body) {
        return body.detail;
      }
    } catch {
      // The response text below remains the most useful available detail.
    }
  }
  return text.trim() || `Erreur HTTP ${response.status}.`;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body === undefined ? {} : { "Content-Type": "application/json" }),
        ...init.headers,
      },
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new ApiError(0, "Impossible de joindre le serveur.", { cause: error });
  }

  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  if (response.status === 204) {
    return null as T;
  }

  const text = await response.text();
  if (!text.trim()) {
    return null as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch (error) {
    throw new ApiError(response.status, "La réponse du serveur est invalide.", {
      cause: error,
    });
  }
}

function appendValue(
  params: URLSearchParams,
  name: string,
  value: string | number | boolean | undefined,
): void {
  if (value !== undefined) {
    params.set(name, String(value));
  }
}

function appendValues(
  params: URLSearchParams,
  name: string,
  values: readonly string[] | undefined,
): void {
  values?.forEach((value) => params.append(name, value));
}

function jobsQuery(filters: JobFilters): string {
  const params = new URLSearchParams();
  appendValue(params, "savedSearchId", filters.savedSearchId);
  appendValue(params, "period", filters.period);
  appendValue(params, "query", filters.query);
  appendValues(params, "location", filters.locations);
  appendValues(params, "contract", filters.contracts);
  appendValue(params, "remote", filters.remote);
  appendValues(params, "experience", filters.experience);
  appendValue(params, "salaryMin", filters.salaryMin);
  appendValues(params, "company", filters.companies);
  appendValues(params, "source", filters.sources);
  appendValues(params, "skill", filters.skills);
  appendValue(params, "duplicateState", filters.duplicateState);
  appendValue(params, "sort", filters.sort);
  appendValue(params, "limit", filters.limit);
  appendValue(params, "offset", filters.offset);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const api = {
  getSearches(options: GetSearchesOptions = {}): Promise<SavedSearch[]> {
    const params = new URLSearchParams();
    appendValue(params, "active", options.active);
    const query = params.toString();
    return request(`/api/searches${query ? `?${query}` : ""}`, {
      signal: options.signal,
    });
  },

  createSearch(payload: SearchCreate, signal?: AbortSignal): Promise<SavedSearch> {
    return request("/api/searches", {
      method: "POST",
      body: JSON.stringify(payload),
      signal,
    });
  },

  updateSearch(
    id: string,
    payload: SearchUpdate,
    signal?: AbortSignal,
  ): Promise<SavedSearch> {
    return request(`/api/searches/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
      signal,
    });
  },

  getJobs(filters: JobFilters = {}, signal?: AbortSignal): Promise<JobsPage> {
    return request(`/api/jobs${jobsQuery(filters)}`, { signal });
  },

  getJob(id: string, signal?: AbortSignal): Promise<JobDetails> {
    return request(`/api/jobs/${encodeURIComponent(id)}`, { signal });
  },

  startSync(payload: StartSyncRequest, signal?: AbortSignal): Promise<SyncRun> {
    return request("/api/syncs", {
      method: "POST",
      body: JSON.stringify(payload),
      signal,
    });
  },

  retrySyncSource(
    runId: string,
    source: SourceName,
    signal?: AbortSignal,
  ): Promise<SyncRun> {
    return request(`/api/syncs/${encodeURIComponent(runId)}/retry`, {
      method: "POST",
      body: JSON.stringify({ source }),
      signal,
    });
  },

  getLatestSync(signal?: AbortSignal): Promise<SyncRun | null> {
    return request("/api/syncs/latest", { signal });
  },
};
