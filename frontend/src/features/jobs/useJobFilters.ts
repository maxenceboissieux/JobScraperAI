import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import type { JobFilters } from "../../api/types";

const FILTER_KEYS = [
  "period",
  "q",
  "lieu",
  "contrat",
  "remote",
  "experience",
  "salaire",
  "entreprise",
  "source",
  "competence",
  "doublon",
  "tri",
] as const;

const PERIODS = ["24h", "3d", "7d", "all"] as const;
const CONTRACTS = [
  "cdi",
  "cdd",
  "interim",
  "stage",
  "alternance",
  "freelance",
  "other",
] as const;
const EXPERIENCES = [
  "internship",
  "junior",
  "mid",
  "senior",
  "lead",
  "director",
] as const;
const SOURCES = [
  "linkedin",
  "hellowork",
  "francetravail",
  "wttj",
  "freework",
  "adzuna",
] as const;
const DUPLICATE_STATES = ["confirmed", "possible", "none"] as const;
const SORTS = ["date", "relevance"] as const;

type Period = JobFilters["period"];
type DuplicateState = NonNullable<JobFilters["duplicateState"]>;
type Sort = NonNullable<JobFilters["sort"]>;

type ParsedFilters = {
  savedSearchId?: string;
  period: Period;
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
  sort: Sort;
};

export type JobFilterValues = {
  period: Period;
  query: string | undefined;
  locations: string[] | undefined;
  contracts: string[] | undefined;
  remote: boolean | undefined;
  experience: string[] | undefined;
  salaryMin: number | undefined;
  companies: string[] | undefined;
  sources: string[] | undefined;
  skills: string[] | undefined;
  duplicateState: DuplicateState | undefined;
  sort: Sort;
};

function isOneOf<T extends string>(
  value: string | null,
  allowed: readonly T[],
): value is T {
  return value !== null && allowed.includes(value as T);
}

function uniqueValues(
  params: URLSearchParams,
  key: string,
  allowed?: readonly string[],
): string[] | undefined {
  const seen = new Set<string>();
  const values: string[] = [];
  for (const raw of params.getAll(key)) {
    const value = raw.trim();
    if (!value || seen.has(value) || (allowed !== undefined && !allowed.includes(value))) {
      continue;
    }
    seen.add(value);
    values.push(value);
  }
  return values.length > 0 ? values : undefined;
}

function parseSalary(value: string | null): number | undefined {
  const normalized = value?.trim() ?? "";
  if (!/^\d+(?:\.\d+)?$/.test(normalized)) {
    return undefined;
  }
  const salary = Number(normalized);
  return Number.isFinite(salary) && salary >= 0 ? salary : undefined;
}

function parseFilters(params: URLSearchParams): ParsedFilters {
  const requestedPeriod = params.get("period");
  const period = isOneOf(requestedPeriod, PERIODS) ? requestedPeriod : "3d";
  const requestedSort = params.get("tri");
  const sort = isOneOf(requestedSort, SORTS) ? requestedSort : "date";
  const requestedDuplicateState = params.get("doublon");
  const duplicateState = isOneOf(requestedDuplicateState, DUPLICATE_STATES)
    ? requestedDuplicateState
    : undefined;
  const query = params.get("q")?.trim() || undefined;
  const requestedRemote = params.get("remote");
  const remote =
    requestedRemote === "true"
      ? true
      : requestedRemote === "false"
        ? false
        : undefined;
  const savedSearchId = params.get("search") || undefined;

  return {
    ...(savedSearchId === undefined ? {} : { savedSearchId }),
    period,
    ...(query === undefined ? {} : { query }),
    ...(uniqueValues(params, "lieu") === undefined
      ? {}
      : { locations: uniqueValues(params, "lieu") }),
    ...(uniqueValues(params, "contrat", CONTRACTS) === undefined
      ? {}
      : { contracts: uniqueValues(params, "contrat", CONTRACTS) }),
    ...(remote === undefined ? {} : { remote }),
    ...(uniqueValues(params, "experience", EXPERIENCES) === undefined
      ? {}
      : { experience: uniqueValues(params, "experience", EXPERIENCES) }),
    ...(parseSalary(params.get("salaire")) === undefined
      ? {}
      : { salaryMin: parseSalary(params.get("salaire")) }),
    ...(uniqueValues(params, "entreprise") === undefined
      ? {}
      : { companies: uniqueValues(params, "entreprise") }),
    ...(uniqueValues(params, "source", SOURCES) === undefined
      ? {}
      : { sources: uniqueValues(params, "source", SOURCES) }),
    ...(uniqueValues(params, "competence") === undefined
      ? {}
      : { skills: uniqueValues(params, "competence") }),
    ...(duplicateState === undefined ? {} : { duplicateState }),
    sort,
  };
}

function appendValues(
  params: URLSearchParams,
  key: string,
  values: readonly string[] | undefined,
) {
  values?.forEach((value) => params.append(key, value));
}

function canonicalParams(
  source: URLSearchParams,
  parsed = parseFilters(source),
): URLSearchParams {
  const next = new URLSearchParams(source);
  FILTER_KEYS.forEach((key) => next.delete(key));
  next.append("period", parsed.period);
  if (parsed.query !== undefined) next.append("q", parsed.query);
  appendValues(next, "lieu", parsed.locations);
  appendValues(next, "contrat", parsed.contracts);
  if (parsed.remote !== undefined) next.append("remote", String(parsed.remote));
  appendValues(next, "experience", parsed.experience);
  if (parsed.salaryMin !== undefined) next.append("salaire", String(parsed.salaryMin));
  appendValues(next, "entreprise", parsed.companies);
  appendValues(next, "source", parsed.sources);
  appendValues(next, "competence", parsed.skills);
  if (parsed.duplicateState !== undefined) {
    next.append("doublon", parsed.duplicateState);
  }
  if (parsed.sort !== "date") next.append("tri", parsed.sort);
  return next;
}

function filterSignature(parsed: ParsedFilters): string {
  return JSON.stringify(parsed);
}

function writeFilter<K extends keyof JobFilterValues>(
  params: URLSearchParams,
  key: K,
  value: JobFilterValues[K],
) {
  const urlKeys: Record<keyof JobFilterValues, string> = {
    period: "period",
    query: "q",
    locations: "lieu",
    contracts: "contrat",
    remote: "remote",
    experience: "experience",
    salaryMin: "salaire",
    companies: "entreprise",
    sources: "source",
    skills: "competence",
    duplicateState: "doublon",
    sort: "tri",
  };
  const urlKey = urlKeys[key];
  params.delete(urlKey);
  if (Array.isArray(value)) {
    value.forEach((item) => params.append(urlKey, item));
  } else if (value !== undefined) {
    params.append(urlKey, String(value));
  }
}

function countActiveFilters(parsed: ParsedFilters): number {
  return [
    parsed.query,
    parsed.locations,
    parsed.contracts,
    parsed.remote,
    parsed.experience,
    parsed.salaryMin,
    parsed.companies,
    parsed.sources,
    parsed.skills,
    parsed.duplicateState,
  ].filter((value) => value !== undefined).length;
}

export function useJobFilters() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchParamsRef = useRef(searchParams);
  const rawSearch = searchParams.toString();
  const navigationIdentity = `${location.key}:${rawSearch}`;
  const parsed = useMemo(() => parseFilters(searchParams), [rawSearch]);
  const [queryDraft, setQueryDraftState] = useState(parsed.query ?? "");
  const queryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const canonical = useMemo(
    () => canonicalParams(searchParams, parsed).toString(),
    [parsed, rawSearch],
  );
  const signature = filterSignature(parsed);
  const [pagination, setPagination] = useState(() => ({ signature, offset: 0 }));
  const offset = pagination.signature === signature ? pagination.offset : 0;
  searchParamsRef.current = searchParams;

  useEffect(() => {
    if (rawSearch !== canonical) {
      setSearchParams(new URLSearchParams(canonical), { replace: true });
    }
  }, [canonical, rawSearch, setSearchParams]);

  useEffect(() => {
    if (pagination.signature !== signature) {
      setPagination({ signature, offset: 0 });
    }
  }, [pagination.signature, signature]);

  const setFilter = useCallback(
    <K extends keyof JobFilterValues>(
      key: K,
      value: JobFilterValues[K],
      options?: { replace?: boolean },
    ) => {
      const currentParams = searchParamsRef.current;
      const currentParsed = parseFilters(currentParams);
      const nextSource = canonicalParams(currentParams, currentParsed);
      writeFilter(nextSource, key, value);
      const nextParsed = parseFilters(nextSource);
      const next = canonicalParams(nextSource, nextParsed);
      if (next.toString() !== canonicalParams(currentParams, currentParsed).toString()) {
        setSearchParams(next, { replace: options?.replace });
      }
    },
    [setSearchParams],
  );

  const clearFilters = useCallback(() => {
    if (queryTimer.current !== null) {
      clearTimeout(queryTimer.current);
      queryTimer.current = null;
    }
    setQueryDraftState("");
    const currentParsed = parseFilters(searchParams);
    const next = canonicalParams(searchParams, {
      ...(currentParsed.savedSearchId === undefined
        ? {}
        : { savedSearchId: currentParsed.savedSearchId }),
      period: currentParsed.period,
      sort: "date",
    });
    if (next.toString() !== canonicalParams(searchParams, currentParsed).toString()) {
      setSearchParams(next);
    }
  }, [searchParams, setSearchParams]);

  const filters = useMemo<JobFilters>(
    () => ({ ...parsed, limit: 24, offset }),
    [offset, parsed],
  );

  useEffect(() => {
    if (queryTimer.current !== null) {
      clearTimeout(queryTimer.current);
      queryTimer.current = null;
    }
    setQueryDraftState(parsed.query ?? "");
    return () => {
      if (queryTimer.current !== null) {
        clearTimeout(queryTimer.current);
        queryTimer.current = null;
      }
    };
  }, [navigationIdentity, parsed.query]);

  const setQueryDraft = useCallback(
    (value: string) => {
      setQueryDraftState(value);
      if (queryTimer.current !== null) {
        clearTimeout(queryTimer.current);
      }
      queryTimer.current = setTimeout(() => {
        queryTimer.current = null;
        const normalized = value.trim();
        setQueryDraftState(normalized);
        setFilter("query", normalized || undefined, { replace: true });
      }, 250);
    },
    [setFilter],
  );

  return {
    filters,
    activeCount: countActiveFilters(parsed),
    setFilter,
    clearFilters,
    queryDraft,
    setQueryDraft,
    setOffset: (nextOffset: number) =>
      setPagination({
        signature,
        offset:
          Number.isSafeInteger(nextOffset) && nextOffset >= 0 ? nextOffset : 0,
      }),
  };
}
