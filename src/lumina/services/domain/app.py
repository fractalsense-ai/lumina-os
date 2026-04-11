"""Domain Authority Service — standalone FastAPI application.

Run standalone::

    uvicorn lumina.services.domain.app:app --port 8004

Or import ``create_app()`` to build a mountable sub-application.
"""

from __future__ import annotations

from fastapi import FastAPI

from lumina.services.domain.routes import router as domain_router
from lumina.services.domain.roles_routes import router as domain_roles_router


def create_app() -> FastAPI:
    """Build the Domain Authority Service FastAPI application."""
    service = FastAPI(
        title="Lumina Domain Authority Service",
        description="Domain lifecycle, physics, session management, and role assignment",
        version="0.4.0",
    )
    service.include_router(domain_router)
    service.include_router(domain_roles_router)
    return service


app = create_app()
