import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { SourceName, SyncRun } from "../../api/types";

const SYNC_RUN_QUERY_KEY = ["sync", "latest"] as const;
const ACTIVE_SYNC_STATUSES = new Set(["pending", "running"]);
const SOURCE_NAMES = new Set<SourceName>([
  "linkedin",
  "hellowork",
  "francetravail",
  "wttj",
  "freework",
  "adzuna",
]);

function isActive(run: SyncRun | null | undefined): boolean {
  return run !== null && run !== undefined && ACTIVE_SYNC_STATUSES.has(run.status);
}

function isSourceName(source: string): source is SourceName {
  return SOURCE_NAMES.has(source as SourceName);
}

function syncRunQueryKey(savedSearchId: string | undefined) {
  return [...SYNC_RUN_QUERY_KEY, savedSearchId ?? null] as const;
}

export function useSyncRun(savedSearchId?: string) {
  const queryClient = useQueryClient();
  const invalidatedProgressVersions = useRef(new Set<string>());
  const [startingSearchCounts, setStartingSearchCounts] = useState(() => new Map<string, number>());
  const latestSyncQuery = useQuery({
    queryKey: syncRunQueryKey(savedSearchId),
    queryFn: ({ signal }) => api.getLatestSync({ savedSearchId, signal }),
    enabled: savedSearchId !== undefined,
    refetchInterval: (query) => (isActive(query.state.data) ? 5_000 : false),
    refetchIntervalInBackground: true,
  });

  const invalidateCompletedSources = useCallback(
    (run: SyncRun, sources = run.sources) => {
      const productive = sources.filter(
        (source) =>
          source.status === "succeeded" ||
          (source.status === "partial" && source.offersPersisted > 0),
      );
      const newCompletions = productive.filter((source) => {
        const key = [
          run.id,
          source.source,
          source.status,
          source.offersPersisted,
          source.finishedAt ?? "",
        ].join(":");
        if (invalidatedProgressVersions.current.has(key)) return false;
        invalidatedProgressVersions.current.add(key);
        return true;
      });
      if (newCompletions.length > 0) {
        void queryClient.invalidateQueries({ queryKey: ["jobs"] });
        void queryClient.invalidateQueries({ queryKey: ["job-details"] });
      }
    },
    [queryClient],
  );

  const startMutation = useMutation({
    mutationFn: (savedSearchId: string) => api.startSync({ savedSearchId }),
    onMutate: async (savedSearchId) => {
      setStartingSearchCounts((counts) => {
        const next = new Map(counts);
        next.set(savedSearchId, (next.get(savedSearchId) ?? 0) + 1);
        return next;
      });
      await queryClient.cancelQueries({ queryKey: syncRunQueryKey(savedSearchId) });
    },
    onSuccess: (run) => {
      queryClient.setQueryData(syncRunQueryKey(run.savedSearchId), run);
      invalidateCompletedSources(run);
    },
    onSettled: (_data, _error, savedSearchId) => {
      setStartingSearchCounts((counts) => {
        const count = counts.get(savedSearchId) ?? 0;
        if (count === 0) return counts;
        const next = new Map(counts);
        if (count === 1) {
          next.delete(savedSearchId);
        } else {
          next.set(savedSearchId, count - 1);
        }
        return next;
      });
    },
  });
  const retryMutation = useMutation({
    mutationFn: ({
      runId,
      source,
    }: {
      runId: string;
      source: SourceName;
      savedSearchId: string;
    }) =>
      api.retrySyncSource(runId, source),
    onMutate: async ({ savedSearchId }) => {
      await queryClient.cancelQueries({ queryKey: syncRunQueryKey(savedSearchId) });
    },
    onSuccess: (run) => {
      queryClient.setQueryData(syncRunQueryKey(run.savedSearchId), run);
      invalidateCompletedSources(run);
    },
  });

  const run = latestSyncQuery.data;
  useEffect(() => {
    if (run !== undefined && run !== null) {
      invalidateCompletedSources(run);
    }
  }, [invalidateCompletedSources, run]);

  const startSync = useCallback(
    (savedSearchId: string) => startMutation.mutateAsync(savedSearchId),
    [startMutation],
  );
  const isStartingSearch = useCallback(
    (savedSearchId: string | undefined) =>
      savedSearchId !== undefined && (startingSearchCounts.get(savedSearchId) ?? 0) > 0,
    [startingSearchCounts],
  );
  const retrySource = useCallback(
    (runId: string, source: string) => {
      if (!isSourceName(source)) {
        return Promise.reject(new Error("La source à relancer est inconnue."));
      }
      const runSearchId = run?.id === runId ? run.savedSearchId : savedSearchId;
      if (runSearchId === undefined) {
        return Promise.reject(new Error("La recherche à synchroniser est inconnue."));
      }
      return retryMutation.mutateAsync({
        runId,
        source,
        savedSearchId: runSearchId,
      });
    },
    [retryMutation, run, savedSearchId],
  );
  const errorMessage = latestSyncQuery.isError
    ? "Impossible de charger l’état de la synchronisation. Les offres affichées restent disponibles."
    : startMutation.isError
      ? "Impossible de démarrer la synchronisation. Réessayez."
      : retryMutation.isError
        ? "Impossible de relancer cette source. Réessayez."
        : null;

  return {
    run: run ?? null,
    errorMessage,
    isStartingSearch,
    isActive: isActive(run),
    isRetrying: retryMutation.isPending,
    startSync,
    retrySource,
    retryLatest: latestSyncQuery.refetch,
  };
}
