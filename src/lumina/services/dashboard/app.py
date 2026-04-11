"""Dashboard Service — standalone FastAPI application.

Run standalone::

    uvicorn lumina.services.dashboard.app:app --port 8005

Or import ``create_app()`` to build a mountable sub-application.
"""

from __future__ import annotations

from fastapi import FastAPI

from lumina.services.dashboard.routes import router as dashboard_router


def create_app() -> FastAPI:
    """Build the Dashboard Service FastAPI application."""
    service = FastAPI(
        title="Lumina Dashboard Service",
        description="System overview, aggregated metrics, and health checks",
        version="0.4.0",
    )
    service.include_router(dashboard_router)
    return service


app = create_app()
