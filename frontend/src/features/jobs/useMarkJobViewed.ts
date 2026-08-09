import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { JobFilters, JobsPage } from "../../api/types";

const ERROR_MESSAGE = "Impossible d’enregistrer cette offre comme déjà vue.";
type Snapshot = readonly [QueryKey, JobsPage | undefined];

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

export function useMarkJobViewed() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (jobId: string) => api.markJobViewed(jobId),
    onMutate: async (jobId) => {
      await queryClient.cancelQueries({ queryKey: ["jobs"] });
      const snapshots = queryClient.getQueriesData<JobsPage>({
        queryKey: ["jobs"],
      }) as Snapshot[];
      const optimisticViewedAt = new Date().toISOString();
      for (const [queryKey, page] of snapshots) {
        const unseenOnly = filtersFromKey(queryKey)?.unseenOnly === true;
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
    onError: (_error, _jobId, context) => {
      for (const [queryKey, page] of context?.snapshots ?? []) {
        queryClient.setQueryData(queryKey, page);
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  return {
    markViewed(jobId: string) {
      mutation.reset();
      mutation.mutate(jobId);
    },
    errorMessage: mutation.isError ? ERROR_MESSAGE : null,
  };
}
