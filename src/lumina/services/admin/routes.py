"""Admin & Escalation Service routes – re-export from monolith.

During the decomposition phase, `lumina.api.routes.admin` remains the
canonical module (too many mock targets in the test suite to replace with
a stub).  This module re-exports the router so the service `app.py`
can mount it.
"""
from lumina.api.routes.admin import router  # noqa: F401

__all__ = ["router"]
