"""Auth Service — standalone FastAPI application.

Run standalone::

    uvicorn lumina.services.auth.app:app --port 8001

Or import ``create_app()`` to build a mountable sub-application for the
gateway.
"""

from __future__ import annotations

from fastapi import FastAPI

from lumina.services.auth.routes import router as auth_router
from lumina.services.auth.admin_routes import router as admin_auth_router


def create_app() -> FastAPI:
    """Build the Auth Service FastAPI application."""
    service = FastAPI(
        title="Lumina Auth Service",
        description="User registration, login, token management, invite/onboarding",
        version="0.4.0",
    )
    service.include_router(auth_router)
    service.include_router(admin_auth_router)
    return service


app = create_app()
