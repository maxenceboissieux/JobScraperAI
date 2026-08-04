"""Asynchronous synchronization launch, retry, and progress routes."""

from __future__ import annotations

from concurrent.futures import Future

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from jobscraper.api.dependencies import get_session
from jobscraper.api.schemas import (
    RetrySyncRequest,
    SourceProgress,
    StartSyncRequest,
    SyncRunResponse,
)
from jobscraper.db.models import SavedSearch, SyncRun
from jobscraper.repositories.sync_runs import SyncRunRepository
from jobscraper.services.sync import ActiveSyncRunError, SyncService

router = APIRouter(prefix="/api/syncs", tags=["syncs"])


def _response(session: Session, run: SyncRun) -> SyncRunResponse:
    """Serialize durable state, filling source rows not started by a worker yet."""

    search = session.get(SavedSearch, run.saved_search_id)
    assert search is not None
    persisted = {
        item.source: item for item in SyncRunRepository(session).source_results(run.id)
    }
    sources = []
    for source in run.requested_sources:
        item = persisted.get(source)
        sources.append(
            SourceProgress(
                source=source,
                status="pending" if item is None else item.status,  # type: ignore[arg-type]
                offers_seen=0 if item is None else item.offers_seen,
                offers_persisted=0 if item is None else item.offers_persisted,
                error_message=None if item is None else item.error_message,
                started_at=None if item is None else item.started_at,
                finished_at=None if item is None else item.finished_at,
            )
        )
    return SyncRunResponse(
        id=run.id,
        saved_search_id=search.id,
        status=run.status,  # type: ignore[arg-type]
        requested_sources=run.requested_sources,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        sources=sources,
    )


def _mark_worker_failure(factory: sessionmaker[Session], run_id: str) -> None:
    """Leave a terminal record even when orchestration itself crashes."""

    with factory() as session:
        try:
            run = SyncRunRepository(session).finish(run_id, status="failed")
            if run is not None:
                session.commit()
        except Exception:
            session.rollback()
            logger.exception("Impossible de finaliser la synchronisation {}", run_id)


def execute_sync(factory: sessionmaker[Session], run_id: str) -> None:
    """Run with worker-owned session; never leak background exceptions silently."""

    with factory() as session:
        try:
            SyncService(session).execute(run_id)
        except Exception:
            session.rollback()
            logger.exception("Échec inattendu de la synchronisation {}", run_id)
            _mark_worker_failure(factory, run_id)


def _observe_future(
    future: Future[None], factory: sessionmaker[Session], run_id: str
) -> None:
    """Force executor exceptions into local logs if a worker wrapper regresses."""

    if future.cancelled():
        with factory() as session:
            try:
                if SyncRunRepository(session).fail_pending(run_id):
                    session.commit()
            except Exception:
                session.rollback()
                logger.exception(
                    "Impossible de finaliser la synchronisation annulée {}", run_id
                )
        return
    try:
        future.result()
    except Exception:
        logger.exception("Une tâche de synchronisation en arrière-plan a échoué")


def _submit(request: Request, run_id: str, session: Session) -> None:
    try:
        future = request.app.state.executor.submit(
            execute_sync, request.app.state.session_factory, run_id
        )
    except Exception as exc:
        logger.opt(exception=exc).error("Soumission de synchronisation refusée")
        if SyncRunRepository(session).fail_pending(run_id):
            session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La synchronisation n’a pas pu être démarrée.",
        ) from None
    future.add_done_callback(
        lambda completed: _observe_future(
            completed, request.app.state.session_factory, run_id
        )
    )


def _start(
    request: Request,
    session: Session,
    *,
    saved_search_id: str,
    sources: set[str] | None,
) -> SyncRunResponse:
    # This avoids SQLite's read-to-write lock upgrade race within one process.
    # The repository's partial unique index remains the durable arbiter.
    with request.app.state.sync_submission_lock:
        service = SyncService(session)
        try:
            run_id = service.create_run(
                saved_search_id, only_sources=sources, reject_active=True
            )
        except ActiveSyncRunError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Une synchronisation est déjà en cours.",
            ) from None
        except LookupError:
            raise HTTPException(
                status_code=404, detail="La recherche enregistrée n’existe pas."
            ) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        run = SyncRunRepository(session).get(run_id)
        assert run is not None
        response = _response(session, run)
        _submit(request, run_id, session)
        return response


@router.get("/latest", response_model=SyncRunResponse | None)
def latest_sync(session: Session = Depends(get_session)) -> SyncRunResponse | None:
    run = SyncRunRepository(session).latest()
    return None if run is None else _response(session, run)


@router.post("", response_model=SyncRunResponse, status_code=status.HTTP_202_ACCEPTED)
def start_sync(
    payload: StartSyncRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> SyncRunResponse:
    return _start(
        request,
        session,
        saved_search_id=payload.saved_search_id,
        sources=None if payload.sources is None else set(payload.sources),
    )


@router.post(
    "/{run_id}/retry",
    response_model=SyncRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_sync(
    run_id: str,
    payload: RetrySyncRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> SyncRunResponse:
    repository = SyncRunRepository(session)
    original = repository.get(run_id)
    if original is None:
        raise HTTPException(
            status_code=404, detail="La synchronisation demandée n’existe pas."
        )
    outcome = next(
        (
            item
            for item in repository.source_results(run_id)
            if item.source == payload.source
        ),
        None,
    )
    if outcome is None or outcome.status not in {"failed", "partial"}:
        raise HTTPException(
            status_code=422,
            detail="Seules les sources en échec ou partielles peuvent être relancées.",
        )
    search = session.get(SavedSearch, original.saved_search_id)
    assert search is not None
    return _start(
        request,
        session,
        saved_search_id=search.id,
        sources={payload.source},
    )


@router.get("/{run_id}", response_model=SyncRunResponse)
def get_sync(run_id: str, session: Session = Depends(get_session)) -> SyncRunResponse:
    run = SyncRunRepository(session).get(run_id)
    if run is None:
        raise HTTPException(
            status_code=404, detail="La synchronisation demandée n’existe pas."
        )
    return _response(session, run)
