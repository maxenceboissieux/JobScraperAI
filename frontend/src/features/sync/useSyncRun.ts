import { useCallback, useEffect, useRef } from "react";
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

type ObservedRun = {
  id: string;
  sourceStatuses: Map<string, string>;
};

function isActive(run: SyncRun | null | undefined): boolean {
  return run !== null && run !== undefined && ACTIVE_SYNC_STATUSES.has(run.status);
}

function isSourceName(source: string): source is SourceName {
  return SOURCE_NAMES.has(source as SourceName);
}

export function useSyncRun() {
  const queryClient = useQueryClient();
  const invalidatedSources = useRef(new Set<string>());
  const observedRun = useRef<ObservedRun | null>(null);
  const latestSyncQuery = useQuery({
    queryKey: SYNC_RUN_QUERY_KEY,
    queryFn: ({ signal }) => api.getLatestSync(signal),
    refetchInterval: (query) => (isActive(query.state.data) ? 5_000 : false),
    refetchIntervalInBackground: true,
  });

  const invalidateCompletedSources = useCallback(
    (run: SyncRun, sources = run.sources) => {
      const completed = sources.filter((source) => source.status === "succeeded");
      const newCompletions = completed.filter((source) => {
        const key = `${run.id}:${source.source}`;
        if (invalidatedSources.current.has(key)) return false;
        invalidatedSources.current.add(key);
        return true;
      });
      if (newCompletions.length > 0) {
        void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      }
    },
    [queryClient],
  );

  const startMutation = useMutation({
    mutationFn: (savedSearchId: string) => api.startSync({ savedSearchId }),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: SYNC_RUN_QUERY_KEY });
    },
    onSuccess: (run) => {
      queryClient.setQueryData(SYNC_RUN_QUERY_KEY, run);
      invalidateCompletedSources(run);
    },
  });
  const retryMutation = useMutation({
    mutationFn: ({ runId, source }: { runId: string; source: SourceName }) =>
      api.retrySyncSource(runId, source),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: SYNC_RUN_QUERY_KEY });
    },
    onSuccess: (run) => {
      queryClient.setQueryData(SYNC_RUN_QUERY_KEY, run);
      invalidateCompletedSources(run);
    },
  });

  const run = latestSyncQuery.data;
  useEffect(() => {
    if (run === undefined || run === null) {
      observedRun.current = null;
      return;
    }
    const previous = observedRun.current;
    invalidateCompletedSources(
      run,
      run.sources.filter(
        (source) =>
          source.status === "succeeded" &&
          (previous?.id !== run.id ||
            previous.sourceStatuses.get(source.source) !== "succeeded"),
      ),
    );
    observedRun.current = {
      id: run.id,
      sourceStatuses: new Map(run.sources.map((source) => [source.source, source.status])),
    };
  }, [invalidateCompletedSources, run]);

  const startSync = useCallback(
    (savedSearchId: string) => startMutation.mutateAsync(savedSearchId),
    [startMutation],
  );
  const retrySource = useCallback(
    (runId: string, source: string) => {
      if (!isSourceName(source)) {
        return Promise.reject(new Error("La source à relancer est inconnue."));
      }
      return retryMutation.mutateAsync({ runId, source });
    },
    [retryMutation],
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
    isStarting: startMutation.isPending,
    isActive: isActive(run),
    isRetrying: retryMutation.isPending,
    startSync,
    retrySource,
    retryLatest: latestSyncQuery.refetch,
  };
}
