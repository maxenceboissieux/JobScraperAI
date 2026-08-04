import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { SavedSearch, SearchCreate, SearchUpdate } from "../api/types";
import { AppHeader } from "../components/AppHeader";
import { JobDetailsDrawer } from "../features/details/JobDetailsDrawer";
import { JobFilters } from "../features/jobs/JobFilters";
import { JobGrid } from "../features/jobs/JobGrid";
import { PeriodTabs } from "../features/jobs/PeriodTabs";
import { useJobFilters } from "../features/jobs/useJobFilters";
import { SearchEditor } from "../features/searches/SearchEditor";
import { SearchSelector } from "../features/searches/SearchSelector";
import { RefreshButton } from "../features/sync/RefreshButton";
import { SyncProgress } from "../features/sync/SyncProgress";
import { useSyncRun } from "../features/sync/useSyncRun";
import "../styles/drawer.css";

const SEARCHES_QUERY_KEY = ["searches"] as const;

type EditorSession =
  | { mode: "create" }
  | { mode: "edit"; searchId: string }
  | null;

function mutationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return "Les informations saisies ne sont pas valides. Vérifiez les champs du formulaire.";
    }
    if (error.status === 0) {
      return "Le service local est injoignable. Vérifiez qu’il est bien démarré.";
    }
    if (error.status === 404) {
      return "La recherche enregistrée n’existe plus. Rechargez la liste puis réessayez.";
    }
    if (error.status >= 500) {
      return "Le service local a rencontré une erreur. Réessayez dans un instant.";
    }
    return "Le service local a refusé l’enregistrement. Vérifiez les informations puis réessayez.";
  }
  return "Une erreur inattendue a empêché l’enregistrement. Réessayez.";
}

function replaceCachedSearch(
  searches: SavedSearch[] | undefined,
  savedSearch: SavedSearch,
  prepend: boolean,
): SavedSearch[] {
  const current = searches ?? [];
  const withoutSavedSearch = current.filter((search) => search.id !== savedSearch.id);
  if (prepend) {
    return [savedSearch, ...withoutSavedSearch];
  }
  const existingIndex = current.findIndex((search) => search.id === savedSearch.id);
  if (existingIndex === -1) {
    return [savedSearch, ...current];
  }
  return current.map((search) =>
    search.id === savedSearch.id ? savedSearch : search,
  );
}

export function App() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const jobFilters = useJobFilters();
  const [editor, setEditor] = useState<EditorSession>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const syncRun = useSyncRun();
  const selectedJobId = searchParams.get("job");
  const selectedJobTrigger = useRef<HTMLElement | null>(null);

  const searchesQuery = useQuery({
    queryKey: SEARCHES_QUERY_KEY,
    queryFn: ({ signal }) => api.getSearches({ signal }),
  });
  const searches = searchesQuery.data ?? [];
  const requestedSearchId = searchParams.get("search");
  const selectedSearch = useMemo(() => {
    const requested = searches.find((search) => search.id === requestedSearchId);
    if (requested !== undefined) {
      return requested;
    }
    if (!searchesQuery.isSuccess) {
      return null;
    }
    return searches.find((search) => search.active) ?? searches[0] ?? null;
  }, [requestedSearchId, searches, searchesQuery.isSuccess]);

  function selectSearch(searchId: string | null, replace = false) {
    const next = new URLSearchParams(searchParams);
    next.delete("search");
    if (searchId !== null) {
      next.append("search", searchId);
    }
    setSearchParams(next, { replace });
  }

  function selectJob(jobId: string) {
    if (
      document.activeElement instanceof HTMLElement &&
      document.activeElement.matches(".job-card__button")
    ) {
      selectedJobTrigger.current = document.activeElement;
    }
    const next = new URLSearchParams(searchParams);
    next.set("job", jobId);
    setSearchParams(next);
  }

  function closeJob() {
    const next = new URLSearchParams(searchParams);
    next.delete("job");
    const trigger = selectedJobTrigger.current;
    setSearchParams(next);
    if (trigger?.isConnected) {
      trigger.focus();
    }
    selectedJobTrigger.current = null;
  }

  useEffect(() => {
    if (!searchesQuery.isSuccess) {
      return;
    }
    const currentIds = searchParams.getAll("search");
    const resolvedId = selectedSearch?.id ?? null;
    const isCanonical =
      resolvedId === null
        ? currentIds.length === 0
        : currentIds.length === 1 && currentIds[0] === resolvedId;
    if (!isCanonical) {
      const next = new URLSearchParams(searchParams);
      next.delete("search");
      if (resolvedId !== null) {
        next.append("search", resolvedId);
      }
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, searchesQuery.isSuccess, selectedSearch, setSearchParams]);

  async function commitServerSearch(savedSearch: SavedSearch, prepend: boolean) {
    await queryClient.cancelQueries({ queryKey: SEARCHES_QUERY_KEY });
    queryClient.setQueryData<SavedSearch[]>(SEARCHES_QUERY_KEY, (current) =>
      replaceCachedSearch(current, savedSearch, prepend),
    );
  }

  const createMutation = useMutation({
    mutationFn: (payload: SearchCreate) => api.createSearch(payload),
    onSuccess: async (created) => {
      await commitServerSearch(created, true);
      selectSearch(created.id);
      setNotice(`La recherche « ${created.name} » a été créée.`);
      void queryClient.invalidateQueries({ queryKey: SEARCHES_QUERY_KEY });
    },
  });

  const editMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: SearchUpdate }) =>
      api.updateSearch(id, payload),
    onSuccess: async (updated) => {
      await commitServerSearch(updated, false);
      setNotice(`La recherche « ${updated.name} » a été mise à jour.`);
      void queryClient.invalidateQueries({ queryKey: SEARCHES_QUERY_KEY });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      api.updateSearch(id, { active }),
    onMutate: () => {
      setActionError(null);
      setNotice(null);
    },
    onSuccess: async (updated) => {
      await commitServerSearch(updated, false);
      setNotice(
        updated.active
          ? `La recherche « ${updated.name} » est réactivée.`
          : `La recherche « ${updated.name} » est suspendue.`,
      );
      void queryClient.invalidateQueries({ queryKey: SEARCHES_QUERY_KEY });
    },
    onError: (error) => {
      setActionError(mutationErrorMessage(error));
    },
  });

  const editedSearch =
    editor?.mode === "edit"
      ? searches.find((search) => search.id === editor.searchId) ?? null
      : null;
  const isSubmitting = createMutation.isPending || editMutation.isPending;
  const submitError =
    editor?.mode === "create"
      ? createMutation.error
        ? mutationErrorMessage(createMutation.error)
        : null
      : editMutation.error
        ? mutationErrorMessage(editMutation.error)
        : null;

  function openCreateEditor() {
    createMutation.reset();
    editMutation.reset();
    setNotice(null);
    setActionError(null);
    setEditor({ mode: "create" });
  }

  function openEditEditor() {
    if (selectedSearch === null) {
      return;
    }
    createMutation.reset();
    editMutation.reset();
    setNotice(null);
    setActionError(null);
    setEditor({ mode: "edit", searchId: selectedSearch.id });
  }

  async function submitEditor(payload: SearchCreate | SearchUpdate) {
    try {
      if (editor?.mode === "create") {
        await createMutation.mutateAsync(payload as SearchCreate);
      } else if (editor?.mode === "edit") {
        await editMutation.mutateAsync({
          id: editor.searchId,
          payload: payload as SearchUpdate,
        });
      } else {
        return;
      }
      setEditor(null);
    } catch {
      // Mutation state keeps the editor open and exposes the translated error.
    }
  }

  function toggleSelectedSearch() {
    if (selectedSearch === null || toggleMutation.isPending) {
      return;
    }
    toggleMutation.mutate({
      id: selectedSearch.id,
      active: !selectedSearch.active,
    });
  }

  const searchControls = (
    <SearchSelector
      searches={searches}
      selectedId={selectedSearch?.id ?? null}
      isLoading={searchesQuery.isPending}
      isBusy={
        createMutation.isPending ||
        editMutation.isPending ||
        toggleMutation.isPending
      }
      onSelect={(searchId) => {
        setNotice(null);
        setActionError(null);
        selectSearch(searchId);
      }}
      onCreate={openCreateEditor}
      onEdit={openEditEditor}
      onToggleActive={toggleSelectedSearch}
    />
  );

  const syncStatus = (
    <SyncProgress
      run={syncRun.run}
      errorMessage={syncRun.errorMessage}
      isRetrying={syncRun.isRetrying}
      onRetryLatest={() => void syncRun.retryLatest()}
      onRetrySource={(source) => {
        if (syncRun.run !== null) {
          void syncRun.retrySource(syncRun.run.id, source).catch(() => undefined);
        }
      }}
    />
  );
  const refreshAction = (
    <RefreshButton
      hasSelectedSearch={selectedSearch !== null}
      isStarting={
        syncRun.isStartingSearch(selectedSearch?.id) ||
        (syncRun.isActive && syncRun.run?.savedSearchId === selectedSearch?.id)
      }
      onRefresh={() => {
        if (selectedSearch !== null) {
          void syncRun.startSync(selectedSearch.id).catch(() => undefined);
        }
      }}
    />
  );

  return (
    <div className="app-shell">
      <AppHeader
        searchControls={searchControls}
        syncStatus={syncStatus}
        refreshAction={refreshAction}
      />

      <main className="app-main" id="contenu-principal">
        <section className="job-filters" aria-label="Filtres des offres">
          <PeriodTabs
            period={jobFilters.filters.period}
            onChange={(period) => jobFilters.setFilter("period", period)}
          />
          <JobFilters
            filters={jobFilters.filters}
            activeCount={jobFilters.activeCount}
            queryDraft={jobFilters.queryDraft}
            setQueryDraft={jobFilters.setQueryDraft}
            setFilter={jobFilters.setFilter}
            clearFilters={jobFilters.clearFilters}
          />
        </section>

        {notice ? (
          <p className="status-banner status-banner--success" role="status">
            {notice}
          </p>
        ) : null}
        {actionError ? (
          <p className="status-banner status-banner--error" role="alert">
            {actionError}
          </p>
        ) : null}

        {searchesQuery.isPending ? (
          <section className="content-state" aria-live="polite">
            <span className="loading-ring" aria-hidden="true" />
            <div>
              <p className="eyebrow">Recherches enregistrées</p>
              <h2>Chargement des recherches…</h2>
            </div>
          </section>
        ) : null}

        {searchesQuery.isError ? (
          <section className="content-state content-state--error" role="alert">
            <div className="content-state__icon" aria-hidden="true">
              !
            </div>
            <div>
              <p className="eyebrow">Service local indisponible</p>
              <h2>Impossible de charger les recherches enregistrées.</h2>
              <p>Vérifiez que l’API locale est démarrée, puis relancez la requête.</p>
              <button
                type="button"
                className="button button--primary"
                onClick={() => void searchesQuery.refetch()}
              >
                Réessayer
              </button>
            </div>
          </section>
        ) : null}

        {searchesQuery.isSuccess && searches.length === 0 ? (
          <section className="content-state content-state--empty">
            <div className="empty-orbit" aria-hidden="true">
              <span />
            </div>
            <div>
              <p className="eyebrow">Première étape</p>
              <h2>Aucune recherche active</h2>
              <p>
                Créez une recherche enregistrée pour préparer vos prochaines
                synchronisations d’offres.
              </p>
              <button
                type="button"
                className="button button--primary"
                onClick={openCreateEditor}
              >
                Créer ma première recherche
              </button>
            </div>
          </section>
        ) : null}

        {searchesQuery.isSuccess && selectedSearch !== null ? (
          <JobGrid
            filters={jobFilters.filters}
            onPageChange={jobFilters.setOffset}
            onSelectJob={selectJob}
          />
        ) : null}
      </main>

      {editor !== null && (editor.mode === "create" || editedSearch !== null) ? (
        <SearchEditor
          key={editor.mode === "create" ? "create" : editor.searchId}
          search={editor.mode === "edit" ? editedSearch : null}
          isSubmitting={isSubmitting}
          submitError={submitError}
          onSubmit={submitEditor}
          onClose={() => setEditor(null)}
        />
      ) : null}

      {selectedJobId !== null ? (
        <JobDetailsDrawer
          jobId={selectedJobId}
          onClose={closeJob}
          onSelectJob={selectJob}
        />
      ) : null}
    </div>
  );
}
