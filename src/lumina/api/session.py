"""Session management: DomainContext, SessionContainer, and session lifecycle."""

from __future__ import annotations

import inspect
import logging
import time
from pathlib import Path
from typing import Any

from lumina.api import config as _cfg
from lumina.api.config import _ensure_user_profile
from lumina.core.ttl_manager import TTLManager, Tier
from lumina.orchestrator.ppa_orchestrator import PPAOrchestrator

log = logging.getLogger("lumina-api")

import os

# Maximum number of domain contexts per session (prevents context-thrashing)
_MAX_CONTEXTS_PER_SESSION = int(os.environ.get("LUMINA_MAX_CONTEXTS_PER_SESSION", "10"))


# ─────────────────────────────────────────────────────────────
# Policy commitment helpers
# ─────────────────────────────────────────────────────────────

def _policy_commitment_payload(runtime: dict[str, Any]) -> dict[str, Any]:
    provenance = dict(runtime.get("runtime_provenance") or {})
    return {
        "subject_id": str(provenance.get("domain_pack_id", "")),
        "subject_version": str(provenance.get("domain_pack_version", "")),
        "subject_hash": str(provenance.get("domain_physics_hash", "")),
    }


def _assert_policy_commitment(runtime: dict[str, Any]) -> None:
    if not _cfg.ENFORCE_POLICY_COMMITMENT:
        return
    payload = _policy_commitment_payload(runtime)
    if not payload["subject_id"] or not payload["subject_hash"]:
        raise RuntimeError("Runtime provenance missing subject_id/subject_hash for policy commitment enforcement")
    has_commitment = _cfg.PERSISTENCE.has_policy_commitment(
        subject_id=payload["subject_id"],
        subject_version=payload.get("subject_version") or None,
        subject_hash=payload["subject_hash"],
    )
    if not has_commitment:
        raise RuntimeError(
            "Policy commitment mismatch: active module domain-physics hash is not log-committed. "
            "Commit the module domain-physics.json hash before activation."
        )


def _assert_system_physics_commitment() -> None:
    if not _cfg.ENFORCE_POLICY_COMMITMENT:
        return
    if _cfg.SYSTEM_PHYSICS_HASH is None:
        return
    if not _cfg.PERSISTENCE.has_system_physics_commitment(_cfg.SYSTEM_PHYSICS_HASH):
        raise RuntimeError(
            "System-physics commitment missing: the active system-physics.json hash is not present in "
            "the system log. Run scripts/seed-system-physics-log.sh (or .ps1 on Windows) before starting the server."
        )


# ─────────────────────────────────────────────────────────────
# Default task generator
# ─────────────────────────────────────────────────────────────

def _default_current_task(
    task_spec: dict[str, Any],
    runtime: dict[str, Any],
    *,
    domain_id: str | None = None,
    task_initializer_fn: Any | None = None,
) -> dict[str, Any]:
    """Create a session-scoped task via the task-initializer adapter hook."""
    if task_initializer_fn is not None:
        try:
            return task_initializer_fn(task_spec, runtime, domain_id=domain_id)
        except Exception:
            log.warning("Task initializer unavailable; falling back to task_spec")
    current_task = task_spec.get("current_task") or task_spec.get("current_problem")
    if isinstance(current_task, dict):
        result = dict(current_task)
        result.setdefault("completed", False)
        return result
    return {
        "task_id": str(task_spec.get("task_id", "task")),
        "status": "in_progress",
        "completed": False,
    }


# ─────────────────────────────────────────────────────────────
# Domain context & session container classes
# ─────────────────────────────────────────────────────────────

class DomainContext:
    """Isolated per-domain state within a session."""

    __slots__ = (
        "orchestrator",
        "task_spec",
        "current_task",
        "turn_count",
        "domain_id",
        "module_key",
        "task_presented_at",
        "subject_profile_path",
    )

    def __init__(
        self,
        orchestrator: Any,
        task_spec: dict[str, Any],
        current_task: dict[str, Any],
        turn_count: int,
        domain_id: str,
        task_presented_at: float,
        subject_profile_path: str = "",
        module_key: str = "",
    ) -> None:
        self.orchestrator = orchestrator
        self.task_spec = task_spec
        self.current_task = current_task
        self.turn_count = turn_count
        self.domain_id = domain_id
        self.module_key = module_key
        self.task_presented_at = task_presented_at
        self.subject_profile_path = subject_profile_path

    def to_session_dict(self) -> dict[str, Any]:
        return {
            "orchestrator": self.orchestrator,
            "task_spec": self.task_spec,
            "current_task": self.current_task,
            "turn_count": self.turn_count,
            "domain_id": self.domain_id,
            "module_key": self.module_key,
            "task_presented_at": self.task_presented_at,
        }

    def sync_from_dict(self, d: dict[str, Any]) -> None:
        self.task_spec = d["task_spec"]
        self.current_task = d["current_task"]
        self.turn_count = d["turn_count"]
        if "module_key" in d:
            self.module_key = d["module_key"]
        if "task_presented_at" in d:
            self.task_presented_at = d["task_presented_at"]


from lumina.session.ring_buffer import ConversationRingBuffer


class SessionContainer:
    """Holds isolated domain contexts for a single session."""

    __slots__ = ("active_domain_id", "contexts", "user", "last_activity", "frozen", "ttl_manager", "consent_accepted", "consent_timestamp", "ring_buffer")

    def __init__(self, active_domain_id: str, user: dict[str, Any] | None = None) -> None:
        self.active_domain_id = active_domain_id
        self.contexts: dict[str, DomainContext] = {}
        self.user = user
        self.last_activity: float = time.time()
        self.frozen: bool = False  # True when an escalation lock is active
        self.ttl_manager: TTLManager = TTLManager()
        self.consent_accepted: bool = False
        self.consent_timestamp: float | None = None
        self.ring_buffer: ConversationRingBuffer = ConversationRingBuffer()

    @property
    def active_context(self) -> DomainContext:
        return self.contexts[self.active_domain_id]


# Global session store
_session_containers: dict[str, SessionContainer] = {}


# ─────────────────────────────────────────────────────────────
# Session lifecycle functions
# ─────────────────────────────────────────────────────────────

def _build_domain_context(
    session_id: str,
    resolved_domain_id: str,
    persisted_state: dict[str, Any] | None = None,
    user: dict[str, Any] | None = None,
) -> DomainContext:
    """Construct a fresh DomainContext for a domain (shared by create + switch)."""
    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)
    _assert_policy_commitment(runtime)
    domain_physics_path = Path(runtime["domain_physics_path"])

    if user is not None:
        domain_key = resolved_domain_id.split("/")[0] if "/" in resolved_domain_id else resolved_domain_id
        # Extract domain role from JWT claim (e.g. {"domain/edu/algebra-level-1/v1": "teacher"})
        _user_domain_roles = user.get("domain_roles") or {}
        _domain_role = _user_domain_roles.get(resolved_domain_id)
        if not _domain_role:
            # Fallback: scan for module-ID keys belonging to this domain
            for _mk in (runtime.get("module_map") or {}):
                if _mk in _user_domain_roles:
                    _domain_role = _user_domain_roles[_mk]
                    break
        subject_profile_path = Path(
            _ensure_user_profile(
                user_id=str(user["sub"]),
                domain_key=domain_key,
                template_path=str(runtime["subject_profile_path"]),
                runtime=runtime,
                domain_role=_domain_role,
                system_role=user.get("role"),
            )
        )
    else:
        subject_profile_path = Path(runtime["subject_profile_path"])

    profile = _cfg.PERSISTENCE.load_subject_profile(str(subject_profile_path))
    _module_map = runtime.get("module_map") or {}
    _resolved_module_key: str | None = None
    _profile_domain_id = profile.get("domain_id") or profile.get("subject_domain_id")
    if _profile_domain_id and _profile_domain_id in _module_map:
        domain_physics_path = Path(_module_map[_profile_domain_id]["domain_physics_path"])
        _resolved_module_key = _profile_domain_id
    elif user is not None:
        # Role-based module routing when profile has no explicit domain_id
        _eff_role = _domain_role
        if not _eff_role:
            _eff_role = _cfg._SYSTEM_ROLE_TO_DOMAIN_ROLE.get(user.get("role", ""))
        _r2m = runtime.get("role_to_default_module") or {}
        _role_mod = _r2m.get(_eff_role or "")
        if _role_mod and _role_mod in _module_map:
            domain_physics_path = Path(_module_map[_role_mod]["domain_physics_path"])
            _resolved_module_key = _role_mod

    domain = _cfg.PERSISTENCE.load_domain_physics(str(domain_physics_path))
    ledger_path = _cfg.PERSISTENCE.get_domain_ledger_path(resolved_domain_id)
    ps = persisted_state or {}

    # ── Per-module adapter overrides (governance modules) ─────
    # If the resolved module has pre-compiled adapter overrides (e.g.
    # governance_adapters.py), use those instead of the shared learning
    # adapters.  This prevents governance roles from hitting ZPD/fluency.
    _mod_entry = _module_map.get(_resolved_module_key or "") or {}
    state_builder = _mod_entry.get("state_builder_fn") or runtime["state_builder_fn"]
    domain_step = _mod_entry.get("domain_step_fn") or runtime["domain_step_fn"]
    domain_params = dict(runtime["domain_step_params"])

    _sb_sig = inspect.signature(state_builder)
    _sb_kwargs: dict[str, Any] = {}
    if "world_sim_cfg" in _sb_sig.parameters:
        _sb_kwargs["world_sim_cfg"] = runtime.get("world_sim")
    if "mud_world_cfg" in _sb_sig.parameters:
        _world_sim = runtime.get("world_sim") or {}
        _sb_kwargs["mud_world_cfg"] = _world_sim.get("mud_world_builder") or None
    if "tiers" in _sb_sig.parameters:
        _tiers = domain.get("subsystem_configs", {}).get("equation_difficulty_tiers") or []
        _ps_task = ps.get("task_spec") or _mod_entry.get("default_task_spec") or runtime.get("default_task_spec") or {}
        _sb_kwargs["tiers"] = _tiers
        _sb_kwargs["tier_progression"] = [str(t.get("tier_id", "")) for t in _tiers]
        _sb_kwargs["nominal_difficulty"] = float(_ps_task.get("nominal_difficulty", 0.5))

    # ── Module-keyed state hydration (two-tier model) ─────────
    # If the profile has module-specific state under modules[module_key],
    # surface it as learning_state so the state builder reads from the
    # module-specific snapshot instead of the flat default.
    _prof_modules = profile.get("modules")
    _mk_state = (_prof_modules if isinstance(_prof_modules, dict) else {}).get(_resolved_module_key or "")
    if isinstance(_mk_state, dict) and _mk_state:
        profile = dict(profile)  # shallow copy — don't mutate cached profile
        profile["learning_state"] = _mk_state

    initial_state = state_builder(profile, **_sb_kwargs)

    orch = PPAOrchestrator(
        domain_physics=domain,
        subject_profile=profile,
        ledger_path=str(ledger_path),
        session_id=session_id,
        domain_lib_step_fn=lambda state, task, ev: domain_step(state, task, ev, domain_params),
        initial_state=initial_state,
        action_prompt_type_map=runtime.get("action_prompt_type_map") or {},
        policy_commitment=_policy_commitment_payload(runtime),
        log_append_callback=lambda sid, record: _cfg.PERSISTENCE.append_log_record(
            sid, record, ledger_path=str(ledger_path),
        ),
        system_physics_hash=_cfg.SYSTEM_PHYSICS_HASH,
    )

    default_task_spec = dict(runtime["default_task_spec"])
    # Prefer module-level default_task_spec declared in runtime-config.yaml
    # (e.g. pre-algebra sets nominal_difficulty: 0.15).
    _mod_task = _mod_entry.get("default_task_spec")
    if isinstance(_mod_task, dict) and _mod_task.get("task_id"):
        default_task_spec = dict(_mod_task)
    # Prefer module-specific task_spec from domain physics (e.g. governance modules
    # define their own under subsystem_configs.governance.default_task_spec).
    _gov_task = (domain.get("subsystem_configs") or {}).get("governance", {}).get("default_task_spec")
    if isinstance(_gov_task, dict) and _gov_task.get("task_id"):
        default_task_spec = dict(_gov_task)
    task_spec = dict(ps.get("task_spec") or default_task_spec)
    # Resolve task_initializer adapter: prefer per-module override, then
    # domain-level adapter, then None (generic fallback in _default_current_task).
    _task_init_fn = _mod_entry.get("task_initializer_fn") or runtime.get("task_initializer_fn")
    # Build a runtime view with the module-specific domain physics so the
    # initializer reads subsystem_configs from the active module.
    _init_runtime = dict(runtime)
    _init_runtime["domain"] = domain
    current_task = dict(
        ps.get("current_task") or ps.get("current_problem")  # backward compat
        or _default_current_task(
            task_spec, _init_runtime,
            domain_id=_resolved_module_key or resolved_domain_id,
            task_initializer_fn=_task_init_fn,
        )
    )
    current_task.setdefault("completed", False)
    turn_count = int(ps.get("turn_count") or 0)
    standing_order_attempts = ps.get("standing_order_attempts") or {}
    if not isinstance(standing_order_attempts, dict):
        standing_order_attempts = {}
    orch.set_standing_order_attempts(standing_order_attempts)

    return DomainContext(
        orchestrator=orch,
        task_spec=task_spec,
        current_task=current_task,
        turn_count=turn_count,
        domain_id=resolved_domain_id,
        task_presented_at=time.time(),
        subject_profile_path=str(subject_profile_path),
        module_key=_resolved_module_key or "",
    )


def _persist_session_container(session_id: str, container: SessionContainer) -> None:
    """Persist all domain contexts in a session container."""
    contexts_state: dict[str, Any] = {}
    for did, ctx in container.contexts.items():
        contexts_state[did] = {
            "task_spec": ctx.task_spec,
            "current_task": ctx.current_task,
            "turn_count": ctx.turn_count,
            "standing_order_attempts": ctx.orchestrator.get_standing_order_attempts(),
            "domain_id": did,
            "module_key": ctx.module_key,
        }
    _cfg.PERSISTENCE.save_session_state(
        session_id,
        {
            "active_domain_id": container.active_domain_id,
            "contexts": contexts_state,
        },
    )


def get_or_create_session(
    session_id: str,
    domain_id: str | None = None,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a legacy-shaped session dict for the requested domain context."""
    if session_id in _session_containers:
        container = _session_containers[session_id]
        resolved = domain_id or container.active_domain_id

        # Touch the active domain context and prune expired ones
        container.ttl_manager.touch(Tier.DOMAIN, resolved)
        for entry in container.ttl_manager.prune():
            expired_did = entry.key
            if expired_did in container.contexts and expired_did != container.active_domain_id:
                del container.contexts[expired_did]
                log.info("[%s] TTL-pruned domain context: %s", session_id, expired_did)

        if resolved != container.active_domain_id:
            previous_domain = container.active_domain_id
            if resolved in container.contexts:
                container.active_domain_id = resolved
                log.info("[%s] Reactivated domain context: %s", session_id, resolved)
            else:
                if len(container.contexts) >= _MAX_CONTEXTS_PER_SESSION:
                    raise RuntimeError(
                        f"Session '{session_id}' has reached the maximum of "
                        f"{_MAX_CONTEXTS_PER_SESSION} domain contexts."
                    )
                resolved_domain_id_checked = _cfg.DOMAIN_REGISTRY.resolve_domain_id(resolved)
                ctx = _build_domain_context(session_id, resolved_domain_id_checked, user=container.user)
                container.contexts[resolved_domain_id_checked] = ctx
                container.active_domain_id = resolved_domain_id_checked
                container.ttl_manager.register(Tier.DOMAIN, resolved_domain_id_checked)
                log.info("[%s] Created new domain context: %s", session_id, resolved_domain_id_checked)
                _persist_session_container(session_id, container)

            _cfg.PERSISTENCE.append_log_record(
                session_id,
                {
                    "event": "domain_switch",
                    "from_domain": previous_domain,
                    "to_domain": container.active_domain_id,
                    "timestamp": time.time(),
                    "session_id": session_id,
                },
                ledger_path=_cfg.PERSISTENCE.get_system_ledger_path(session_id),
            )

        return container.active_context.to_session_dict()

    # New session
    resolved_domain_id = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    _persisted = _cfg.PERSISTENCE.load_session_state(session_id) or {}
    _persisted_ctx = (_persisted.get("contexts") or {}).get(resolved_domain_id) or None
    ctx = _build_domain_context(session_id, resolved_domain_id, persisted_state=_persisted_ctx, user=user)

    container = SessionContainer(active_domain_id=resolved_domain_id, user=user)
    container.contexts[resolved_domain_id] = ctx
    _session_containers[session_id] = container

    # Configure TTL manager from domain physics temporal_policy
    _tp = (ctx.orchestrator.domain or {}).get("temporal_policy")
    if _tp:
        container.ttl_manager = TTLManager.from_temporal_policy(_tp)
    container.ttl_manager.register(Tier.DOMAIN, resolved_domain_id)

    _persist_session_container(session_id, container)
    log.info("Created new session: %s (domain=%s)", session_id, resolved_domain_id)
    return container.active_context.to_session_dict()


def _close_session(session_id: str, actor_id: str, actor_role: str, close_type: str = "normal", close_reason: str | None = None) -> None:
    """Close a session: write CommitmentRecords and remove from memory."""
    from lumina.system_log.admin_operations import build_commitment_record

    container = _session_containers.get(session_id)
    if container is None:
        return

    if container.contexts:
        for did, ctx in container.contexts.items():
            # ── Flush final orchestrator state to the user profile ──
            if container.user is not None and ctx.orchestrator.state is not None and ctx.subject_profile_path:
                try:
                    _runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(did)
                    _mm = _runtime.get("module_map") or {}
                    _mod = _mm.get(ctx.module_key) or {}
                    _ps_fn = (
                        _mod.get("profile_serializer_fn")
                        or _runtime.get("profile_serializer_fn")
                    )
                    _profile_data = _cfg.PERSISTENCE.load_subject_profile(ctx.subject_profile_path)
                    if _ps_fn is not None:
                        _profile_data = _ps_fn(
                            orch_state=ctx.orchestrator.state,
                            profile_data=_profile_data,
                            module_key=ctx.module_key,
                        )
                    else:
                        import dataclasses
                        if dataclasses.is_dataclass(ctx.orchestrator.state):
                            _profile_data["session_state"] = dataclasses.asdict(ctx.orchestrator.state)
                        elif isinstance(ctx.orchestrator.state, dict):
                            _profile_data["session_state"] = dict(ctx.orchestrator.state)
                    _cfg.PERSISTENCE.save_subject_profile(ctx.subject_profile_path, _profile_data)
                except Exception:
                    log.debug("Profile flush on close failed for %s/%s", session_id, did)

            record = build_commitment_record(
                actor_id=actor_id,
                actor_role=actor_role,
                commitment_type="session_close",
                subject_id=session_id,
                summary=f"Session closed ({close_type}): domain {did}",
                close_type=close_type,
                close_reason=close_reason,
                metadata={"domain_id": did, "turn_count": ctx.turn_count},
            )
            try:
                _cfg.PERSISTENCE.append_log_record(
                    session_id, record,
                    ledger_path=_cfg.PERSISTENCE.get_domain_ledger_path(did),
                )
            except Exception:
                log.debug("Could not write session_close record for %s/%s", session_id, did)
    else:
        record = build_commitment_record(
            actor_id=actor_id,
            actor_role=actor_role,
            commitment_type="session_close",
            subject_id=session_id,
            summary=f"Session closed ({close_type}): no domain contexts",
            close_type=close_type,
            close_reason=close_reason,
        )
        _cfg.PERSISTENCE.append_system_log_record(record)

    _persist_session_container(session_id, container)
    # Explicitly wipe the ring buffer before dropping the container
    container.ring_buffer.clear()
    del _session_containers[session_id]
