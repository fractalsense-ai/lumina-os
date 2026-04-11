"""Admin ops – re-export from monolith for standalone service use."""
from lumina.api.routes.ops import (  # noqa: F401
    admin_daemon,
    admin_escalations,
    admin_ingestion,
    admin_invite,
    admin_physics,
    admin_profile,
    admin_queries,
    admin_rbac,
)
