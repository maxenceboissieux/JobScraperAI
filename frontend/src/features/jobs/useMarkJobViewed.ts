import { useRef, useState } from "react";
import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { JobCard, JobFilters, JobsPage } from "../../api/types";

const ERROR_MESSAGE = "Impossible d’enregistrer cette offre comme déjà vue.";
type AffectedPageSnapshot = {
  queryKey: QueryKey;
  previousJob: JobCard;
  previousIndex: number;
  optimisticViewedAt: string;
  unseenOnly: boolean;
};

function filtersFromKey(queryKey: QueryKey): JobFilters | undefined {
  const candidate = queryKey[1];
  return typeof candidate === "object" && candidate !== null
    ? (candidate as JobFilters)
    : undefined;
}

function markPageViewed(
  page: JobsPage | undefined,
  jobId: string,
  viewedAt: string,
  unseenOnly: boolean,
  replaceViewedAt = false,
): JobsPage | undefined {
  if (page === undefined || !page.items.some((job) => job.id === jobId)) {
    return page;
  }
  if (unseenOnly) {
    return {
      ...page,
      items: page.items.filter((job) => job.id !== jobId),
      total: Math.max(0, page.total - 1),
    };
  }
  return {
    ...page,
    items: page.items.map((job) =>
      job.id === jobId
        ? {
            ...job,
            viewedAt: replaceViewedAt ? viewedAt : (job.viewedAt ?? viewedAt),
          }
        : job,
    ),
  };
}

function rollbackPage(
  page: JobsPage | undefined,
  jobId: string,
  snapshot: AffectedPageSnapshot,
): JobsPage | undefined {
  if (page === undefined) {
    return page;
  }
  if (snapshot.unseenOnly) {
    if (page.items.some((job) => job.id === jobId)) {
      return page;
    }
    const items = [...page.items];
    items.splice(
      Math.min(snapshot.previousIndex, items.length),
      0,
      snapshot.previousJob,
    );
    return {
      ...page,
      items,
      total: page.total + 1,
    };
  }
  if (
    !page.items.some(
      (job) =>
        job.id === jobId && job.viewedAt === snapshot.optimisticViewedAt,
    )
  ) {
    return page;
  }
  return {
    ...page,
    items: page.items.map((job) =>
      job.id === jobId
        ? { ...job, viewedAt: snapshot.previousJob.viewedAt }
        : job,
    ),
  };
}

export function useMarkJobViewed() {
  const queryClient = useQueryClient();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const inFlightByJobId = useRef(new Map<string, Promise<unknown>>());
  const activeMarkCount = useRef(0);
  const mutation = useMutation({
    mutationFn: (jobId: string) => api.markJobViewed(jobId),
    onMutate: async (jobId) => {
      await queryClient.cancelQueries({ queryKey: ["jobs"] });
      const optimisticViewedAt = new Date().toISOString();
      const snapshots: AffectedPageSnapshot[] = [];
      for (const [queryKey, page] of queryClient.getQueriesData<JobsPage>({
        queryKey: ["jobs"],
      })) {
        const previousIndex = page?.items.findIndex((job) => job.id === jobId) ?? -1;
        if (page === undefined || previousIndex < 0) {
          continue;
        }
        const unseenOnly = filtersFromKey(queryKey)?.unseenOnly === true;
        snapshots.push({
          queryKey,
          previousJob: page.items[previousIndex],
          previousIndex,
          optimisticViewedAt,
          unseenOnly,
        });
        queryClient.setQueryData(
          queryKey,
          markPageViewed(page, jobId, optimisticViewedAt, unseenOnly),
        );
      }
      return { snapshots };
    },
    onSuccess: (viewed) => {
      const pages = queryClient.getQueriesData<JobsPage>({ queryKey: ["jobs"] });
      for (const [queryKey, page] of pages) {
        queryClient.setQueryData(
          queryKey,
          markPageViewed(
            page,
            viewed.id,
            viewed.viewedAt,
            filtersFromKey(queryKey)?.unseenOnly === true,
            true,
          ),
        );
      }
    },
    onError: (_error, jobId, context) => {
      for (const snapshot of context?.snapshots ?? []) {
        queryClient.setQueryData<JobsPage>(snapshot.queryKey, (page) =>
          rollbackPage(page, jobId, snapshot),
        );
      }
      setErrorMessage(ERROR_MESSAGE);
    },
  });

  return {
    markViewed(jobId: string) {
      if (inFlightByJobId.current.has(jobId)) {
        return;
      }
      setErrorMessage(null);
      activeMarkCount.current += 1;
      const request = mutation.mutateAsync(jobId);
      inFlightByJobId.current.set(jobId, request);
      void request
        .catch(() => undefined)
        .finally(() => {
          if (inFlightByJobId.current.get(jobId) === request) {
            inFlightByJobId.current.delete(jobId);
          }
          activeMarkCount.current -= 1;
          if (activeMarkCount.current === 0) {
            void queryClient.invalidateQueries({ queryKey: ["jobs"] });
          }
        });
    },
    errorMessage,
  };
}
