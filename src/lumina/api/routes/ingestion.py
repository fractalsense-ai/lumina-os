"""Ingestion routes – thin re-export stub.

Canonical implementation lives in `lumina.services.ingestion.routes`.
"""
from lumina.services.ingestion.routes import (  # noqa: F401
    _detect_content_type,
    _get_ingest_service,
    router,
)

__all__ = ["router", "_get_ingest_service", "_detect_content_type"]
