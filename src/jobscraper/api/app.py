"""FastAPI application factory and local-only Uvicorn entry point."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger

from jobscraper.api.routes import jobs, searches, syncs
from jobscraper.runtime import DEFAULT_DATABASE_URL, build_runtime

DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_app(
    database_url: str | None = None, frontend_dist: str | Path | None = None
) -> FastAPI:
    """Build the local aggregation API with an app-owned database/executor."""

    resolved_database_url = (
        database_url or os.getenv("JOBSCRAPER_DATABASE_URL") or DEFAULT_DATABASE_URL
    )
    runtime = build_runtime(resolved_database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        executor: ThreadPoolExecutor | None = None
        try:
            runtime.migrate()
            executor = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="jobscraper-sync"
            )
            app.state.executor = executor
            yield
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
            runtime.close()

    app = FastAPI(title="JobScraper API", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.engine = runtime.engine
    app.state.session_factory = runtime.session_factory
    # SQLite cannot safely upgrade two simultaneous read transactions to writes.
    # The database partial unique index remains the cross-process authority.
    app.state.sync_submission_lock = Lock()
    app.include_router(searches.router)
    app.include_router(jobs.router)
    app.include_router(syncs.router)

    resolved_frontend_dist = Path(frontend_dist or DEFAULT_FRONTEND_DIST).resolve()
    frontend_assets = resolved_frontend_dist / "assets"
    frontend_index = resolved_frontend_dist / "index.html"
    if frontend_assets.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=frontend_assets),
            name="frontend-assets",
        )

    @app.api_route(
        "/{client_path:path}", methods=["GET", "HEAD"], include_in_schema=False
    )
    async def frontend(client_path: str) -> Response:
        if client_path == "api" or client_path.startswith("api/"):
            raise HTTPException(status_code=404)
        if client_path == "assets" or client_path.startswith("assets/"):
            raise HTTPException(status_code=404)
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        return HTMLResponse(
            status_code=503,
            content=(
                "<h1>Interface web indisponible</h1>"
                "<p>Depuis le dossier <code>frontend</code>, lancez "
                "<code>pnpm install</code> puis <code>pnpm build</code>, "
                "et redémarrez l’API.</p>"
            ),
        )

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.opt(exception=exc).error("Erreur API non gérée")
        return JSONResponse(
            status_code=500, content={"detail": "Une erreur interne est survenue."}
        )

    return app


def run() -> None:
    """Start the local-only server used by the desktop automation."""

    database_url = os.getenv("JOBSCRAPER_DATABASE_URL")
    uvicorn.run(create_app(database_url), host="127.0.0.1", port=8000)
