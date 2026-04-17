"""Shared context object for admin operation handlers.

Both system-level operation modules and domain-pack operation handlers
receive an ``AdminOperationContext`` instead of importing system internals
directly.  This keeps domain packs decoupled from the API layer.

See docs/7-concepts/command-execution-pipeline.md
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool


log = logging.getLogger("lumina.admin-context")


@dataclass
class AdminOperationContext:
    """Everything an operation handler needs — no direct imports required."""

    # Core services
    persistence: Any  # lumina.api.config.PERSISTENCE (or ScopedPersistenceAdapter for domain ops)
    domain_registry: Any  # lumina.api.config.DOMAIN_REGISTRY

    # Governance helpers (from lumina.system_log.admin_operations)
    can_govern_domain: Callable[..., bool]
    build_commitment_record: Callable[..., dict[str, Any]]
    map_role_to_actor_role: Callable[[str], str]
    build_trace_event: Callable[..., dict[str, Any]]
    build_domain_role_assignment: Callable[..., dict[str, Any]]
    build_domain_role_revocation: Callable[..., dict[str, Any]]
    canonical_sha256: Callable[..., str]

    # Profile resolution
    resolve_user_profile_path: Callable[..., Path]

    # Capability checks
    has_domain_capability: Callable[..., bool]
    has_escalation_capability: Callable[..., bool]

    # Session invalidation (e.g. after /switch module)
    rebuild_domain_context: Callable[[str, str], None] | None = None

    # Domain scoping — set when dispatching to a domain-pack handler
    domain_id: str | None = None

    # Async helpers
    run_in_threadpool: Callable[..., Awaitable[Any]] = field(default=run_in_threadpool)

    # Standard HTTP error
    HTTPException: type = field(default=HTTPException)

    # Logger
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("lumina.admin-ops"))
