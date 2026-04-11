"""System Log Service — standalone FastAPI application.

Run standalone::

    uvicorn lumina.services.system_log.app:app --port 8002

Or import ``create_app()`` to build a mountable sub-application.
"""

from __future__ import annotations

from fastapi import FastAPI

from lumina.services.system_log.routes import router as system_log_router
from lumina.services.system_log.events_routes import router as events_router


def create_app() -> FastAPI:
    """Build the System Log Service FastAPI application."""
    service = FastAPI(
        title="Lumina System Log Service",
        description="Append-only log, hash-chain validation, SSE streaming, audit",
        version="0.4.0",
    )
    service.include_router(system_log_router)
    service.include_router(events_router)
    return service


app = create_app()
