"""Auth endpoints -- re-export stub.

The implementation has moved to `lumina.services.auth.routes`.
This module re-exports the router for backward compatibility with
`server.py` and existing test imports.
"""

from lumina.services.auth.routes import router  # noqa: F401
