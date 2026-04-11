"""Ingestion Service — standalone FastAPI application.

Run standalone::

    uvicorn lumina.services.ingestion.app:app --port 8003

Or import ``create_app()`` to build a mountable sub-application.
"""

from __future__ import annotations

from fastapi import FastAPI

from lumina.services.ingestion.routes import router as ingestion_router
from lumina.services.ingestion.staging_routes import router as staging_router


def create_app() -> FastAPI:
    """Build the Ingestion Service FastAPI application."""
    service = FastAPI(
        title="Lumina Ingestion Service",
        description="File upload, extraction, staged review, domain pack commit",
        version="0.4.0",
    )
    service.include_router(ingestion_router)
    service.include_router(staging_router)
    return service


app = create_app()
