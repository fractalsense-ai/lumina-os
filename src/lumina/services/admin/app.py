"""Admin & Escalation Service — standalone FastAPI application.

Run standalone::

    uvicorn lumina.services.admin.app:app --port 8006

Or import ``create_app()`` to build a mountable sub-application.
"""

from __future__ import annotations

from fastapi import FastAPI

from lumina.services.admin.routes import router as admin_router


def create_app() -> FastAPI:
    """Build the Admin & Escalation Service FastAPI application."""
    service = FastAPI(
        title="Lumina Admin & Escalation Service",
        description="Admin commands, escalation resolution, user management ops",
        version="0.4.0",
    )
    service.include_router(admin_router)
    return service


app = create_app()
