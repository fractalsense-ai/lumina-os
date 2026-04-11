"""SSE event stream -- re-export stub.

The implementation has moved to `lumina.services.system_log.events_routes`.
This module re-exports the router for backward compatibility.
"""

from lumina.services.system_log.events_routes import (  # noqa: F401
    _hash_token,
    _sse_tokens,
    router,
)
