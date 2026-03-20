"""
lumina-api-server.py — Project Lumina Integration Server

Generic runtime host for D.S.A. orchestration:
- Loads runtime behavior from domain-owned config
- Keeps core server free of domain-specific prompt/state logic
- Routes each turn through orchestrator prompt contracts and System Log
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from lumina.auth.auth import (
    AuthError,
    TokenExpiredError,
    TokenInvalidError,
    VALID_ROLES,
    create_jwt,
    hash_password,
    revoke_token_jti,
    verify_jwt,
    verify_password,
)
from lumina.system_log.admin_operations import (
    build_commitment_record,
    build_trace_event,
    can_govern_domain,
    map_role_to_actor_role,
    _canonical_sha256 as admin_canonical_sha256,
)
from lumina.core.domain_registry import DomainNotFoundError, DomainRegistry
from lumina.persistence.filesystem import FilesystemPersistenceAdapter
from lumina.core.permissions import Operation, check_permission
from lumina.persistence.adapter import PersistenceAdapter
from lumina.core.runtime_loader import load_runtime_context
from lumina.core.yaml_loader import load_yaml
from lumina.core.slm import (
    TaskWeight,
    call_slm,
    classify_task_weight,
    slm_available,
    slm_interpret_physics_context,
    slm_parse_admin_command,
    slm_render_glossary,
    ADMIN_OPERATIONS,
)
from lumina.systools.manifest_integrity import check_manifest_report, regen_manifest_report

# ─────────────────────────────────────────────────────────────
# Resolve paths and imports
# ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]

from lumina.orchestrator.ppa_orchestrator import PPAOrchestrator

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

LLM_PROVIDER = os.environ.get("LUMINA_LLM_PROVIDER", "openai")
OPENAI_MODEL = os.environ.get("LUMINA_OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL = os.environ.get("LUMINA_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
RUNTIME_CONFIG_PATH = os.environ.get("LUMINA_RUNTIME_CONFIG_PATH")
_explicit_registry = os.environ.get("LUMINA_DOMAIN_REGISTRY_PATH")
# Default to the standard registry path only when neither explicit config is set.
# If LUMINA_RUNTIME_CONFIG_PATH is set, honour single-domain mode (registry=None).
DOMAIN_REGISTRY_PATH: str | None = (
    _explicit_registry
    if _explicit_registry
    else (None if RUNTIME_CONFIG_PATH else "cfg/domain-registry.yaml")
)
PERSISTENCE_BACKEND = os.environ.get("LUMINA_PERSISTENCE_BACKEND", "filesystem").strip().lower()
DB_URL = os.environ.get("LUMINA_DB_URL")
ENFORCE_POLICY_COMMITMENT = os.environ.get("LUMINA_ENFORCE_POLICY_COMMITMENT", "true").strip().lower() not in {"0", "false", "no"}

_SYSTEM_PHYSICS_PATH = Path(os.environ.get("LUMINA_SYSTEM_PHYSICS_PATH", str(_REPO_ROOT / "cfg" / "system-physics.json")))
try:
    with open(_SYSTEM_PHYSICS_PATH, encoding="utf-8") as _fh:
        _system_physics_data = json.load(_fh)
    SYSTEM_PHYSICS_HASH: str | None = hashlib.sha256(
        json.dumps(_system_physics_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
except Exception:
    log.warning("Could not load system-physics.json from %s; system-physics gate disabled.", _SYSTEM_PHYSICS_PATH)
    SYSTEM_PHYSICS_HASH = None
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("LUMINA_CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
BOOTSTRAP_MODE: bool = os.environ.get("LUMINA_BOOTSTRAP_MODE", "true").strip().lower() not in {"0", "false", "no"}

# Session idle timeout (minutes). 0 = disabled.
SESSION_IDLE_TIMEOUT_MINUTES: int = int(os.environ.get("LUMINA_SESSION_IDLE_TIMEOUT_MINUTES", "30"))

# ─────────────────────────────────────────────────────────────
# Domain Registry (replaces single-domain RUNTIME singleton)
# ─────────────────────────────────────────────────────────────

DOMAIN_REGISTRY = DomainRegistry(
    repo_root=_REPO_ROOT,
    registry_path=DOMAIN_REGISTRY_PATH,
    single_config_path=RUNTIME_CONFIG_PATH,
    load_runtime_context_fn=load_runtime_context,
)

_DEFAULT_LOG_DIR = Path(tempfile.gettempdir()) / "lumina-log"
LOG_DIR = Path(os.environ.get("LUMINA_LOG_DIR", os.environ.get("LUMINA_CTL_DIR", str(_DEFAULT_LOG_DIR))))
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _build_persistence_adapter() -> PersistenceAdapter:
    if PERSISTENCE_BACKEND == "sqlite":
        from lumina.persistence.sqlite import SQLitePersistenceAdapter

        return SQLitePersistenceAdapter(repo_root=_REPO_ROOT, database_url=DB_URL)
    return FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, log_dir=LOG_DIR)


PERSISTENCE: PersistenceAdapter = _build_persistence_adapter()


# ─────────────────────────────────────────────────────────────
# Per-user profile helpers
# ─────────────────────────────────────────────────────────────

_PROFILES_DIR = _REPO_ROOT / "cfg" / "profiles"


def _resolve_user_profile_path(user_id: str, domain_key: str) -> Path:
    """Return ``cfg/profiles/{user_id}/{domain_key}.yaml`` under the repo root."""
    safe_uid = user_id.replace("/", "_").replace("\\", "_")
    safe_domain = domain_key.replace("/", "_").replace("\\", "_")
    return _PROFILES_DIR / safe_uid / f"{safe_domain}.yaml"


def _ensure_user_profile(user_id: str, domain_key: str, template_path: str) -> str:
    """Return a user-specific profile path, copying template if not yet created."""
    target = _resolve_user_profile_path(user_id, domain_key)
    if not target.exists():
        import shutil
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template_path, target)
        log.info("Initialised profile for user=%s domain=%s at %s", user_id, domain_key, target)
    return str(target)


def _default_current_problem(task_spec: dict[str, Any], runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a session-scoped problem via the domain-registered generator.

    Falls back to task_spec's ``current_problem`` and then to a generic
    placeholder.  The core never encodes domain-specific task shapes — the
    domain is responsible for populating ``task_spec.current_problem`` or
    registering a ``generate_problem`` tool function.
    """
    # Try the domain-registered generator (opaque to the core — domain provides
    # the fn and receives its own subsystem_configs so it can extract what it needs).
    if runtime is not None:
        gen_fn = (runtime.get("tool_fns") or {}).get("generate_problem")
        if gen_fn is not None:
            try:
                difficulty = float(task_spec.get("nominal_difficulty", 0.5))
                subsystem_configs = (runtime.get("domain") or {}).get("subsystem_configs") or {}
                return gen_fn(difficulty, subsystem_configs)
            except Exception:
                log.warning("Problem generator unavailable; falling back to task_spec")

    # Use whatever current_problem is already in the task_spec.
    current_problem = task_spec.get("current_problem")
    if isinstance(current_problem, dict):
        return dict(current_problem)

    # Generic placeholder — the domain is responsible for supplying task state.
    return {
        "task_id": str(task_spec.get("task_id", "task")),
        "status": "in_progress",
    }


def _canonical_sha256(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_LATEX_INLINE_RE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_LATEX_DISPLAY_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_LATEX_DOLLAR2_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_LATEX_DOLLAR_RE = re.compile(r"\$([^$\n]+)\$")
_LATEX_FRAC_RE = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
_LATEX_CMD_BRACE_RE = re.compile(r"\\[a-zA-Z]+\{([^{}]*)\}")


def _strip_latex_delimiters(text: str) -> str:
    """Convert LaTeX math notation to plain-text equivalents.

    Removes delimiter pairs (\\(…\\), \\[…\\], $…$, $$…$$), converts
    \\frac{a}{b} → (a)/(b), and strips remaining LaTeX commands with braces
    so the student-facing response never contains raw markup.
    """
    # Display delimiters first (longer pattern takes priority over inline $)
    text = _LATEX_DOLLAR2_RE.sub(r"\1", text)
    text = _LATEX_DISPLAY_RE.sub(r"\1", text)
    # Inline delimiters
    text = _LATEX_DOLLAR_RE.sub(r"\1", text)
    text = _LATEX_INLINE_RE.sub(r"\1", text)
    # \frac{a}{b} → (a)/(b); repeat to handle one level of nesting
    for _ in range(3):
        text = _LATEX_FRAC_RE.sub(r"(\1)/(\2)", text)
    # \left and \right sizing hints — drop entirely
    text = re.sub(r"\\left\s*", "", text)
    text = re.sub(r"\\right\s*", "", text)
    # Common symbols
    text = text.replace(r"\cdot", "*").replace(r"\times", "*")
    # Generic \\cmd{content} → content (catches \text{}, \sqrt{}, etc.)
    text = _LATEX_CMD_BRACE_RE.sub(r"\1", text)
    return text


# ── Glossary query detection ─────────────────────────────────

_GLOSSARY_QUERY_RE = re.compile(
    r"(?:what\s+(?:is|are|does)\s+(?:a|an|the)?\s*)"
    r"|(?:what\s+does\s+.+?\s+mean)"
    r"|(?:define\s+)"
    r"|(?:meaning\s+of\s+)"
    r"|(?:what(?:'s| is)\s+)",
    re.IGNORECASE,
)


def _detect_glossary_query(
    message: str,
    glossary: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Match a student message against the domain glossary.

    Returns the matched glossary entry dict or None.
    Matching is case-insensitive against ``term`` and ``aliases``.
    """
    if not glossary:
        return None

    text = message.strip()
    if not _GLOSSARY_QUERY_RE.search(text):
        return None

    # Build a lookup index: lowered term/alias → glossary entry.
    # For aliases starting with a leading article, also index the stripped form.
    _ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)
    index: dict[str, dict[str, Any]] = {}
    for entry in glossary:
        key = str(entry.get("term", "")).lower().strip()
        if key:
            index[key] = entry
        for alias in entry.get("aliases") or []:
            akey = str(alias).lower().strip()
            if akey:
                index[akey] = entry
                stripped = _ARTICLE_RE.sub("", akey).strip()
                if stripped and stripped != akey:
                    index[stripped] = entry

    # Normalise the question to extract the candidate term.
    candidate = text.lower()
    # Strip trailing punctuation
    candidate = re.sub(r"[?.!]+$", "", candidate).strip()
    # Strip common question prefixes
    candidate = re.sub(
        r"^(?:what\s+(?:is|are|does)\s+(?:an|a|the)?\s*"
        r"|what\s+does\s+|what(?:'s| is)\s+(?:an|a|the)?\s*"
        r"|define\s+|meaning\s+of\s+)",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip()
    # Strip trailing "mean" from "what does X mean"
    candidate = re.sub(r"\s+mean$", "", candidate).strip()

    if not candidate:
        return None

    # Exact match
    if candidate in index:
        return index[candidate]

    # Plural fallback: strip trailing 's'
    if candidate.endswith("s") and candidate[:-1] in index:
        return index[candidate[:-1]]

    return None


def _policy_commitment_payload(runtime: dict[str, Any]) -> dict[str, Any]:
    provenance = dict(runtime.get("runtime_provenance") or {})
    return {
        "subject_id": str(provenance.get("domain_pack_id", "")),
        "subject_version": str(provenance.get("domain_pack_version", "")),
        "subject_hash": str(provenance.get("domain_physics_hash", "")),
    }


def _assert_policy_commitment(runtime: dict[str, Any]) -> None:
    if not ENFORCE_POLICY_COMMITMENT:
        return
    payload = _policy_commitment_payload(runtime)
    if not payload["subject_id"] or not payload["subject_hash"]:
        raise RuntimeError("Runtime provenance missing subject_id/subject_hash for policy commitment enforcement")

    has_commitment = PERSISTENCE.has_policy_commitment(
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
    if not ENFORCE_POLICY_COMMITMENT:
        return
    if SYSTEM_PHYSICS_HASH is None:
        return
    if not PERSISTENCE.has_system_physics_commitment(SYSTEM_PHYSICS_HASH):
        raise RuntimeError(
            "System-physics commitment missing: the active system-physics.json hash is not present in "
            "the system log. Run scripts/seed-system-physics-log.ps1 before starting the server."
        )


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _coerce_int(value: Any, default: int = 0, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


def _coerce_float(
    value: Any, default: float = 0.0, minimum: float | None = None, maximum: float | None = None
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def _coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _normalize_turn_data(
    turn_data: dict[str, Any],
    turn_input_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply domain-owned schema rules; otherwise preserve values as-is."""
    normalized = dict(turn_data)
    schema = turn_input_schema or {}
    if not isinstance(schema, dict):
        return normalized

    for field, raw_cfg in schema.items():
        if not isinstance(raw_cfg, dict):
            continue

        field_type = str(raw_cfg.get("type", "")).strip().lower()
        has_field = field in normalized
        value = normalized.get(field)

        if (not has_field or value is None) and "default" in raw_cfg:
            value = raw_cfg.get("default")
            normalized[field] = value

        if value is None:
            continue

        if field_type == "bool":
            normalized[field] = _coerce_bool(value, bool(raw_cfg.get("default", False)))
            continue

        if field_type == "int":
            minimum = raw_cfg.get("minimum")
            minimum_int = int(minimum) if isinstance(minimum, (int, float)) else None
            normalized[field] = _coerce_int(value, int(raw_cfg.get("default", 0)), minimum_int)
            continue

        if field_type == "float":
            minimum = raw_cfg.get("minimum")
            maximum = raw_cfg.get("maximum")
            min_float = float(minimum) if isinstance(minimum, (int, float)) else None
            max_float = float(maximum) if isinstance(maximum, (int, float)) else None
            normalized[field] = _coerce_float(value, float(raw_cfg.get("default", 0.0)), min_float, max_float)
            continue

        if field_type == "string":
            normalized[field] = _coerce_str(value, str(raw_cfg.get("default", "")))
            continue

        if field_type == "enum":
            values = raw_cfg.get("values")
            if isinstance(values, list):
                allowed = [str(v) for v in values]
                rendered = str(value)
                if rendered not in allowed and "default" in raw_cfg:
                    rendered = str(raw_cfg.get("default"))
                normalized[field] = rendered
            continue

        if field_type == "list":
            if isinstance(value, list):
                normalized[field] = value
            elif "default" in raw_cfg and isinstance(raw_cfg.get("default"), list):
                normalized[field] = list(raw_cfg.get("default"))
            else:
                normalized[field] = []

    return normalized

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("lumina-api")

# ─────────────────────────────────────────────────────────────
# LLM Client Abstraction
# ─────────────────────────────────────────────────────────────


def _call_openai(system: str, user: str, model: str | None = None) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    client = OpenAI()
    response = client.chat.completions.create(
        model=model or OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.4,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


def _call_anthropic(system: str, user: str, model: str | None = None) -> str:
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    client = Anthropic()
    response = client.messages.create(
        model=model or ANTHROPIC_MODEL,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=0.4,
        max_tokens=1024,
    )
    return response.content[0].text


def _validate_provider_api_key(provider: str) -> None:
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required for live anthropic mode. "
                "Set the key in your runtime environment. "
                "Deterministic mode (deterministic_response=true) does not require provider keys."
            )
        return

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is required for live openai mode. "
            "Set the key in your runtime environment. "
            "Deterministic mode (deterministic_response=true) does not require provider keys."
        )


def call_llm(system: str, user: str, model: str | None = None) -> str:
    _validate_provider_api_key(LLM_PROVIDER)
    if LLM_PROVIDER == "anthropic":
        return _call_anthropic(system, user, model)
    return _call_openai(system, user, model)


# ─────────────────────────────────────────────────────────────
# Runtime-driven helpers
# ─────────────────────────────────────────────────────────────


def render_contract_response(prompt_contract: dict[str, Any], runtime: dict[str, Any]) -> str:
    """Deterministic fallback driven by domain runtime config templates."""
    prompt_type = str(prompt_contract.get("prompt_type", "default"))
    task_id = str(prompt_contract.get("task_id", "task"))
    templates = runtime["deterministic_templates"]

    template = templates.get(prompt_type) or templates.get("default") or "Continue with {task_id}."
    try:
        return template.format(task_id=task_id, prompt_type=prompt_type)
    except KeyError:
        return template


def interpret_turn_input(input_text: str, task_context: dict[str, Any], runtime: dict[str, Any], world_sim_theme: dict[str, Any] | None = None, mud_world_state: dict[str, Any] | None = None) -> dict[str, Any]:
    interpreter = runtime["turn_interpreter_fn"]
    kwargs: dict[str, Any] = {
        "call_llm": call_llm,
        "input_text": input_text,
        "task_context": task_context,
        "prompt_text": runtime["turn_interpretation_prompt"],
        "default_fields": runtime["turn_input_defaults"],
        "tool_fns": runtime.get("tool_fns"),
    }
    _interp_sig = inspect.signature(interpreter)
    if "call_slm" in _interp_sig.parameters:
        kwargs["call_slm"] = call_slm
    nlp_fn = runtime.get("nlp_pre_interpreter_fn")
    if nlp_fn is not None:
        kwargs["nlp_pre_interpreter_fn"] = nlp_fn
    if world_sim_theme:
        kwargs["world_sim_theme"] = world_sim_theme
    if mud_world_state and "mud_world_state" in _interp_sig.parameters:
        kwargs["mud_world_state"] = mud_world_state
    return interpreter(**kwargs)


def invoke_runtime_tool(tool_id: str, payload: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    tool_fns: dict[str, Any] = runtime.get("tool_fns") or {}
    tool_fn = tool_fns.get(tool_id)
    if tool_fn is None:
        raise RuntimeError(f"Unknown tool adapter: {tool_id}")
    result = tool_fn(payload)
    if not isinstance(result, dict):
        raise RuntimeError(f"Tool adapter '{tool_id}' must return a dict result")
    return result


_TPL_RE = re.compile(r"\{([^{}]+)\}")


def _resolve_context_path(context: dict[str, Any], path_expr: str) -> Any:
    cur: Any = context
    for part in path_expr.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _render_template_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        matches = _TPL_RE.findall(value)
        if not matches:
            return value

        # Single placeholder keeps source type (for numeric and boolean tool payloads).
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}") and len(matches) == 1:
            return _resolve_context_path(context, matches[0])

        rendered = value
        for match in matches:
            resolved = _resolve_context_path(context, match)
            rendered = rendered.replace("{" + match + "}", "" if resolved is None else str(resolved))
        return rendered
    if isinstance(value, dict):
        return {k: _render_template_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_template_value(v, context) for v in value]
    return value


def apply_tool_call_policy(
    resolved_action: str,
    prompt_contract: dict[str, Any],
    turn_data: dict[str, Any],
    task_spec: dict[str, Any],
    runtime: dict[str, Any],
) -> list[dict[str, Any]]:
    policies: dict[str, Any] = runtime.get("tool_call_policies") or {}
    entries = policies.get(resolved_action) or []
    if not isinstance(entries, list):
        return []

    context = {
        "action": resolved_action,
        "prompt_contract": prompt_contract,
        "turn_data": turn_data,
        "task_spec": task_spec,
    }

    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool_id = entry.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id:
            continue
        payload = _render_template_value(entry.get("payload") or {}, context)
        if not isinstance(payload, dict):
            payload = {}
        tool_result = invoke_runtime_tool(tool_id, payload, runtime)
        results.append({"tool_id": tool_id, "payload": payload, "result": tool_result})
    return results


# ─────────────────────────────────────────────────────────────
# Session Manager — multi-domain context support
# ─────────────────────────────────────────────────────────────

# Maximum number of domain contexts per session (prevents context-thrashing)
_MAX_CONTEXTS_PER_SESSION = int(os.environ.get("LUMINA_MAX_CONTEXTS_PER_SESSION", "10"))


class DomainContext:
    """Isolated per-domain state within a session."""

    __slots__ = (
        "orchestrator",
        "task_spec",
        "current_problem",
        "turn_count",
        "domain_id",
        "problem_presented_at",
        "subject_profile_path",
    )

    def __init__(
        self,
        orchestrator: Any,
        task_spec: dict[str, Any],
        current_problem: dict[str, Any],
        turn_count: int,
        domain_id: str,
        problem_presented_at: float,
        subject_profile_path: str = "",
    ) -> None:
        self.orchestrator = orchestrator
        self.task_spec = task_spec
        self.current_problem = current_problem
        self.turn_count = turn_count
        self.domain_id = domain_id
        self.problem_presented_at = problem_presented_at
        self.subject_profile_path = subject_profile_path

    def to_session_dict(self) -> dict[str, Any]:
        """Return a dict matching the legacy session shape for process_message()."""
        return {
            "orchestrator": self.orchestrator,
            "task_spec": self.task_spec,
            "current_problem": self.current_problem,
            "turn_count": self.turn_count,
            "domain_id": self.domain_id,
            "problem_presented_at": self.problem_presented_at,
        }

    def sync_from_dict(self, d: dict[str, Any]) -> None:
        """Update mutable fields from the session dict after process_message mutations."""
        self.task_spec = d["task_spec"]
        self.current_problem = d["current_problem"]
        self.turn_count = d["turn_count"]
        if "problem_presented_at" in d:
            self.problem_presented_at = d["problem_presented_at"]


class SessionContainer:
    """Holds isolated domain contexts for a single session."""

    __slots__ = ("active_domain_id", "contexts", "user", "last_activity")

    def __init__(self, active_domain_id: str, user: dict[str, Any] | None = None) -> None:
        self.active_domain_id = active_domain_id
        self.contexts: dict[str, DomainContext] = {}
        self.user = user
        self.last_activity: float = time.time()

    @property
    def active_context(self) -> DomainContext:
        return self.contexts[self.active_domain_id]


_session_containers: dict[str, SessionContainer] = {}


def _build_domain_context(
    session_id: str,
    resolved_domain_id: str,
    persisted_state: dict[str, Any] | None = None,
    user: dict[str, Any] | None = None,
) -> DomainContext:
    """Construct a fresh DomainContext for a domain (shared by create + switch)."""
    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)

    _assert_policy_commitment(runtime)
    domain_physics_path = Path(runtime["domain_physics_path"])

    # Resolve profile: per-user file when authenticated, default path otherwise
    if user is not None:
        domain_key = resolved_domain_id.split("/")[0] if "/" in resolved_domain_id else resolved_domain_id
        subject_profile_path = Path(
            _ensure_user_profile(
                user_id=str(user["sub"]),
                domain_key=domain_key,
                template_path=str(runtime["subject_profile_path"]),
            )
        )
    else:
        subject_profile_path = Path(runtime["subject_profile_path"])

    # Load profile early so we can use domain_id for module routing.
    profile = PERSISTENCE.load_subject_profile(str(subject_profile_path))

    # Module routing: if the student profile declares a domain_id that maps to a
    # different module in the runtime module_map, override domain_physics_path.
    _module_map = runtime.get("module_map") or {}
    _profile_domain_id = profile.get("domain_id") or profile.get("subject_domain_id")
    if _profile_domain_id and _profile_domain_id in _module_map:
        domain_physics_path = Path(_module_map[_profile_domain_id]["domain_physics_path"])

    domain = PERSISTENCE.load_domain_physics(str(domain_physics_path))
    ledger_path = PERSISTENCE.get_log_ledger_path(session_id, domain_id=resolved_domain_id)
    ps = persisted_state or {}

    state_builder = runtime["state_builder_fn"]
    domain_step = runtime["domain_step_fn"]
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
        _ps_task = ps.get("task_spec") or runtime.get("default_task_spec") or {}
        _sb_kwargs["tiers"] = _tiers
        _sb_kwargs["tier_progression"] = [str(t.get("tier_id", "")) for t in _tiers]
        _sb_kwargs["nominal_difficulty"] = float(_ps_task.get("nominal_difficulty", 0.5))
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
        log_append_callback=lambda sid, record: PERSISTENCE.append_log_record(
            sid,
            record,
            ledger_path=str(ledger_path),
        ),
        system_physics_hash=SYSTEM_PHYSICS_HASH,
    )

    default_task_spec = dict(runtime["default_task_spec"])
    task_spec = dict(ps.get("task_spec") or default_task_spec)
    current_problem = dict(ps.get("current_problem") or _default_current_problem(task_spec, runtime))
    turn_count = int(ps.get("turn_count") or 0)
    standing_order_attempts = ps.get("standing_order_attempts") or {}
    if not isinstance(standing_order_attempts, dict):
        standing_order_attempts = {}
    orch.set_standing_order_attempts(standing_order_attempts)

    return DomainContext(
        orchestrator=orch,
        task_spec=task_spec,
        current_problem=current_problem,
        turn_count=turn_count,
        domain_id=resolved_domain_id,
        problem_presented_at=time.time(),
        subject_profile_path=str(subject_profile_path),
    )


def get_or_create_session(
    session_id: str,
    domain_id: str | None = None,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a legacy-shaped session dict for the requested domain context.

    If the session already exists and the requested domain differs from
    the active domain, a domain switch is performed (creating a new
    context if needed).
    """
    if session_id in _session_containers:
        container = _session_containers[session_id]
        resolved = domain_id or container.active_domain_id

        if resolved != container.active_domain_id:
            # ── Domain switch ────────────────────────────────
            previous_domain = container.active_domain_id

            if resolved in container.contexts:
                # Reactivate previously visited domain
                container.active_domain_id = resolved
                log.info(
                    "[%s] Reactivated domain context: %s",
                    session_id,
                    resolved,
                )
            else:
                # Create new domain context
                if len(container.contexts) >= _MAX_CONTEXTS_PER_SESSION:
                    raise RuntimeError(
                        f"Session '{session_id}' has reached the maximum of "
                        f"{_MAX_CONTEXTS_PER_SESSION} domain contexts."
                    )
                resolved_domain_id_checked = DOMAIN_REGISTRY.resolve_domain_id(resolved)
                ctx = _build_domain_context(session_id, resolved_domain_id_checked, user=container.user)
                container.contexts[resolved_domain_id_checked] = ctx
                container.active_domain_id = resolved_domain_id_checked
                log.info(
                    "[%s] Created new domain context: %s",
                    session_id,
                    resolved_domain_id_checked,
                )
                # Persist the new context
                _persist_session_container(session_id, container)

            # Record the domain switch event in the meta-ledger
            PERSISTENCE.append_log_record(
                session_id,
                {
                    "event": "domain_switch",
                    "from_domain": previous_domain,
                    "to_domain": container.active_domain_id,
                    "timestamp": time.time(),
                    "session_id": session_id,
                },
                ledger_path=PERSISTENCE.get_log_ledger_path(session_id, domain_id="_meta"),
            )

        return container.active_context.to_session_dict()

    # ── New session ──────────────────────────────────────────
    resolved_domain_id = DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    # Restore persisted context so the student continues with the same equation
    # even if the session was evicted from memory (idle timeout / restart).
    _persisted = PERSISTENCE.load_session_state(session_id) or {}
    _persisted_ctx = (_persisted.get("contexts") or {}).get(resolved_domain_id) or None
    ctx = _build_domain_context(session_id, resolved_domain_id, persisted_state=_persisted_ctx, user=user)

    container = SessionContainer(active_domain_id=resolved_domain_id, user=user)
    container.contexts[resolved_domain_id] = ctx
    _session_containers[session_id] = container

    _persist_session_container(session_id, container)
    log.info("Created new session: %s (domain=%s)", session_id, resolved_domain_id)

    return container.active_context.to_session_dict()


def _persist_session_container(session_id: str, container: SessionContainer) -> None:
    """Persist all domain contexts in a session container."""
    contexts_state: dict[str, Any] = {}
    for did, ctx in container.contexts.items():
        contexts_state[did] = {
            "task_spec": ctx.task_spec,
            "current_problem": ctx.current_problem,
            "turn_count": ctx.turn_count,
            "standing_order_attempts": ctx.orchestrator.get_standing_order_attempts(),
            "domain_id": did,
        }
    PERSISTENCE.save_session_state(
        session_id,
        {
            "active_domain_id": container.active_domain_id,
            "contexts": contexts_state,
        },
    )


# ─────────────────────────────────────────────────────────────
# Core Integration — D.S.A. -> LLM pipeline
# ─────────────────────────────────────────────────────────────


def process_message(
    session_id: str,
    input_text: str,
    turn_data_override: dict[str, Any] | None = None,
    deterministic_response: bool = False,
    domain_id: str | None = None,
    user: dict[str, Any] | None = None,
    model_id: str | None = None,
    model_version: str | None = None,
) -> dict[str, Any]:
    session = get_or_create_session(session_id, domain_id=domain_id, user=user)
    orch: PPAOrchestrator = session["orchestrator"]
    task_spec: dict[str, Any] = session["task_spec"]
    current_problem: dict[str, Any] = session["current_problem"]

    # Resolve per-session runtime context
    resolved_domain_id = session["domain_id"]
    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)
    runtime_provenance = dict(runtime.get("runtime_provenance") or {})
    system_prompt = runtime["system_prompt"]

    # ── Glossary interception (neutral turn — no mastery/affect change) ──
    domain_physics = runtime.get("domain") or {}
    glossary = domain_physics.get("glossary") or []
    glossary_match = _detect_glossary_query(input_text, glossary)
    if glossary_match is not None:
        prompt_contract = {
            "prompt_type": "definition_lookup",
            "domain_pack_id": str(domain_physics.get("id", "")),
            "domain_pack_version": str(domain_physics.get("version", "")),
            "task_id": str(task_spec.get("task_id", "")),
            "glossary_entry": {
                "term": glossary_match.get("term", ""),
                "definition": glossary_match.get("definition", ""),
                "example_in_context": glossary_match.get("example_in_context", ""),
                "related_terms": glossary_match.get("related_terms") or [],
            },
        }
        llm_payload = dict(prompt_contract)
        llm_payload["current_problem"] = current_problem

        if deterministic_response:
            template = runtime.get("deterministic_templates", {}).get("definition_lookup")
            if template:
                llm_response = template.format(**prompt_contract.get("glossary_entry", {}))
            else:
                entry = prompt_contract["glossary_entry"]
                llm_response = (
                    f"{entry['term'].title()}: {entry['definition']} "
                    f"Example: {entry['example_in_context']}"
                )
        elif slm_available():
            llm_response = slm_render_glossary(prompt_contract["glossary_entry"])
        else:
            # SLM unavailable — fall back to deterministic template.
            entry = prompt_contract["glossary_entry"]
            llm_response = (
                f"{entry['term'].title()}: {entry['definition']} "
                f"Example: {entry['example_in_context']}"
            )

        llm_response = _strip_latex_delimiters(llm_response)
        session["turn_count"] += 1
        return {
            "response": llm_response,
            "action": "definition_lookup",
            "prompt_type": "definition_lookup",
            "escalated": False,
            "tool_results": None,
            "domain_id": resolved_domain_id,
        }

    task_context = dict(task_spec)
    task_context["current_problem"] = current_problem
    if turn_data_override is not None:
        turn_data = turn_data_override
    elif deterministic_response:
        turn_data = dict(runtime.get("turn_input_defaults") or {})
    elif runtime.get("local_only"):
        # local_only domains use the SLM for turn classification when available;
        # they never call the external LLM for any purpose.
        if slm_available():
            _li_interpreter = runtime["turn_interpreter_fn"]
            _li_sig = inspect.signature(_li_interpreter)
            _li_kwargs: dict[str, Any] = {
                "call_llm": call_slm,
                "input_text": input_text,
                "task_context": task_context,
                "prompt_text": runtime["turn_interpretation_prompt"],
                "default_fields": runtime["turn_input_defaults"],
                "tool_fns": runtime.get("tool_fns"),
            }
            if "call_slm" in _li_sig.parameters:
                _li_kwargs["call_slm"] = call_slm
            turn_data = _li_interpreter(**_li_kwargs)
        else:
            turn_data = dict(runtime.get("turn_input_defaults") or {})
    else:
        world_sim_theme = getattr(orch.state, "world_sim_theme", {})
        mud_world_state = getattr(orch.state, "mud_world_state", {})
        turn_data = interpret_turn_input(input_text, task_context, runtime, world_sim_theme=world_sim_theme, mud_world_state=mud_world_state)
    turn_data = _normalize_turn_data(turn_data, runtime.get("turn_input_schema") or {})

    # ── SLM physics interpretation (context compression) ─────
    # Skipped for local_only domains — turn data is already fully structured.
    if not runtime.get("local_only") and slm_available():
        slm_context = slm_interpret_physics_context(
            incoming_signals=turn_data,
            domain_physics=domain_physics,
            glossary=glossary,
        )
        turn_data["_slm_context"] = slm_context

    # Inject server-side solve elapsed time (more reliable than LLM estimate)
    presented_at = session.get("problem_presented_at")
    if presented_at is not None:
        _elapsed = time.time() - presented_at
        if (runtime.get("tool_fns") or {}).get("generate_problem") is not None:
            turn_data["solve_elapsed_sec"] = _elapsed
        # response_latency_sec measures wall-clock time from prompt delivery to
        # response receipt — the same interval as solve_elapsed_sec.
        turn_data["response_latency_sec"] = _elapsed

    log.info("[%s] Turn Data: %s", session_id, json.dumps(turn_data, default=str))

    turn_provenance: dict[str, Any] = dict(runtime_provenance)
    turn_provenance["turn_data_hash"] = _canonical_sha256(turn_data)
    if model_id is not None:
        turn_provenance["model_id"] = model_id
    if model_version is not None:
        turn_provenance["model_version"] = model_version

    # Determine weight tier for this turn's prompt type (resolved after
    # orchestrator produces the prompt contract, but we need provenance now).
    slm_weight_overrides = runtime.get("slm_weight_overrides") or {}

    prompt_contract, resolved_action = orch.process_turn(
        task_spec,
        turn_data,
        provenance_metadata=turn_provenance,
    )

    # ── Override action to task_complete when the adapter signals problem_solved ──
    # Reads only the engine contract field `problem_solved` — domain-agnostic.
    if turn_data.get("problem_solved") is True:
        resolved_action = "task_complete"
        prompt_contract["prompt_type"] = "task_complete"

    reported_status = turn_data.get("problem_status")
    if isinstance(reported_status, str) and reported_status.strip():
        current_problem["status"] = reported_status.strip()

    # ── Fluency-gated problem advancement ─────────────────────
    fluency_decision = {}
    domain_lib_decision = getattr(orch, "last_domain_lib_decision", None) or {}
    if isinstance(domain_lib_decision.get("fluency"), dict):
        fluency_decision = domain_lib_decision["fluency"]

    should_advance = fluency_decision.get("advanced", False)

    if should_advance or turn_data.get("problem_solved") is True:
        domain = (runtime.get("domain") or {}).get("subsystem_configs") or {}
        tiers = domain.get("equation_difficulty_tiers")
        if isinstance(tiers, list) and tiers:
            try:
                gen_fn = (runtime.get("tool_fns") or {}).get("generate_problem")
                if gen_fn is not None:
                    if should_advance:
                        next_tier = fluency_decision.get("next_tier", "")
                        tier_objs = {str(t.get("tier_id")): t for t in tiers}
                        target_tier = tier_objs.get(next_tier, tiers[-1])
                        diff = (float(target_tier.get("min_difficulty", 0)) +
                                float(target_tier.get("max_difficulty", 1))) / 2
                        task_spec["nominal_difficulty"] = diff
                    else:
                        diff = float(task_spec.get("nominal_difficulty", 0.5))
                    current_problem = gen_fn(diff, domain)
            except Exception:
                log.warning("Problem generation on advance failed", exc_info=True)
        session["problem_presented_at"] = time.time()

    session["current_problem"] = current_problem
    session["turn_count"] += 1

    # Sync mutations back to the DomainContext in the session container
    container = _session_containers.get(session_id)
    if container is not None:
        container.active_context.sync_from_dict(session)
        container.last_activity = time.time()
        _persist_session_container(session_id, container)

        # ── Auto-save per-user profile after each turn ────────
        if container.user is not None and orch.state is not None:
            profile_path = container.active_context.subject_profile_path
            if profile_path:
                try:
                    import dataclasses
                    profile_data = PERSISTENCE.load_subject_profile(profile_path)
                    if dataclasses.is_dataclass(orch.state):
                        _ls_dict = dataclasses.asdict(orch.state)
                        # .fluency is a dynamic attribute — not a dataclass field —
                        # so dataclasses.asdict() silently omits it.  Merge manually.
                        if hasattr(orch.state, "fluency"):
                            _ls_dict["fluency"] = {
                                "current_tier": orch.state.fluency.current_tier,
                                "consecutive_correct": orch.state.fluency.consecutive_correct,
                            }
                        profile_data["learning_state"] = _ls_dict
                    else:
                        # Non-dataclass state (e.g. plain dict from system domain).
                        # Save minimal session fields; there is no learning model to persist.
                        _sd = orch.state if isinstance(orch.state, dict) else {}
                        profile_data["session_state"] = {
                            "turn_count": int(_sd.get("turn_count", 0)),
                            "operator_id": str(_sd.get("operator_id", "")),
                        }
                    PERSISTENCE.save_subject_profile(profile_path, profile_data)
                except Exception:
                    log.warning("Profile auto-save failed for session %s", session_id)
    else:
        PERSISTENCE.save_session_state(
            session_id,
            {
                "task_spec": task_spec,
                "current_problem": current_problem,
                "turn_count": session["turn_count"],
                "last_action": resolved_action,
                "standing_order_attempts": orch.get_standing_order_attempts(),
                "domain_id": resolved_domain_id,
            },
        )

    log.info(
        "[%s] Turn %s: action=%s, prompt_type=%s",
        session_id,
        session["turn_count"],
        resolved_action,
        prompt_contract.get("prompt_type"),
    )

    escalated = any(
        r.get("record_type") == "EscalationRecord" and r.get("session_id") == session_id
        for r in orch.log_records[-2:]
    )

    tool_results = apply_tool_call_policy(
        resolved_action=resolved_action,
        prompt_contract=prompt_contract,
        turn_data=turn_data,
        task_spec=task_spec,
        runtime=runtime,
    )

    llm_payload = dict(prompt_contract)
    llm_payload["current_problem"] = current_problem
    llm_payload["student_message"] = input_text
    if tool_results:
        llm_payload["tool_results"] = tool_results

    if deterministic_response:
        llm_response = render_contract_response(prompt_contract, runtime)
    else:
        # ── Weight-routed dispatch: SLM for low-weight, LLM for high. ──
        prompt_type = str(prompt_contract.get("prompt_type", "task_presentation"))
        weight = classify_task_weight(prompt_type, overrides=slm_weight_overrides)
        if weight is TaskWeight.LOW and slm_available():
            llm_response = call_slm(
                system=system_prompt,
                user=json.dumps(llm_payload, indent=2, ensure_ascii=False),
            )
            from lumina.core.slm import SLM_MODEL as _slm_model_name
            turn_provenance["slm_model_id"] = _slm_model_name
        elif runtime.get("local_only"):
            # local_only domains never call an external LLM regardless of weight tier.
            if slm_available():
                llm_response = call_slm(
                    system=system_prompt,
                    user=json.dumps(llm_payload, indent=2, ensure_ascii=False),
                )
                from lumina.core.slm import SLM_MODEL as _slm_model_name
                turn_provenance["slm_model_id"] = _slm_model_name
            else:
                llm_response = render_contract_response(prompt_contract, runtime)
        else:
            llm_response = call_llm(
                system=system_prompt,
                user=json.dumps(llm_payload, indent=2, ensure_ascii=False),
            )

    llm_response = _strip_latex_delimiters(llm_response)

    log.info("[%s] Response length: %s chars", session_id, len(llm_response))

    post_payload_provenance = dict(turn_provenance)
    post_payload_provenance["prompt_contract_hash"] = _canonical_sha256(prompt_contract)
    post_payload_provenance["tool_results_hash"] = _canonical_sha256(tool_results)
    post_payload_provenance["llm_payload_hash"] = _canonical_sha256(llm_payload)
    post_payload_provenance["response_hash"] = _canonical_sha256(llm_response)
    orch.append_provenance_trace(
        task_id=str(task_spec.get("task_id", "")),
        action=resolved_action,
        prompt_type=str(prompt_contract.get("prompt_type", "task_presentation")),
        metadata=post_payload_provenance,
    )

    return {
        "response": llm_response,
        "action": resolved_action,
        "prompt_type": prompt_contract.get("prompt_type", "task_presentation"),
        "escalated": escalated,
        "tool_results": tool_results,
        "domain_id": resolved_domain_id,
    }


# ─────────────────────────────────────────────────────────────
# FastAPI Application
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Project Lumina API",
    description="D.S.A. Orchestrator + LLM Conversational Interface (multi-domain)",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    deterministic_response: bool = False
    turn_data_override: dict[str, Any] | None = None
    domain_id: str | None = None
    model_id: str | None = None
    model_version: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    action: str
    prompt_type: str
    escalated: bool
    tool_results: list[dict[str, Any]] | None = None
    domain_id: str | None = None
    structured_content: dict[str, Any] | None = None


class ToolRequest(BaseModel):
    payload: dict[str, Any]


class ToolResponse(BaseModel):
    tool_id: str
    result: dict[str, Any]


class SystemLogValidateResponse(BaseModel):
    result: dict[str, Any]


class ManifestCheckResponse(BaseModel):
    passed: bool
    ok_count: int
    pending_count: int
    missing_count: int
    mismatch_count: int
    entries: list[dict[str, Any]]


class ManifestRegenResponse(BaseModel):
    updated_count: int
    missing_paths: list[str]
    manifest_path: str


# ── Auth request/response models ─────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    governed_modules: list[str] | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str


class UserResponse(BaseModel):
    user_id: str
    username: str
    role: str
    governed_modules: list[str]
    active: bool


# ── Admin request/response models ────────────────────────────

class UpdateUserRequest(BaseModel):
    role: str | None = None
    governed_modules: list[str] | None = None


class RevokeRequest(BaseModel):
    user_id: str | None = None


class PasswordResetRequest(BaseModel):
    user_id: str | None = None
    new_password: str


class DomainCommitRequest(BaseModel):
    domain_id: str
    actor_id: str | None = None
    summary: str | None = None


class DomainPhysicsUpdateRequest(BaseModel):
    updates: dict[str, Any]
    summary: str


class EscalationResolveRequest(BaseModel):
    decision: str  # "approve", "reject", "defer"
    reasoning: str


class AdminCommandRequest(BaseModel):
    instruction: str


class CommandResolveRequest(BaseModel):
    action: str  # "accept" | "reject" | "modify"
    modified_schema: dict[str, Any] | None = None


class LogicScrapeRequest(BaseModel):
    prompt: str
    iterations: int | None = None
    domain_id: str


# ── Auth middleware ───────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = None,
) -> dict[str, Any] | None:
    """Extract and verify JWT from Authorization header.

    Returns the decoded token payload or None when no token is provided
    (allows endpoints to choose whether auth is required).
    """
    if credentials is None:
        return None
    try:
        payload = verify_jwt(credentials.credentials)
    except TokenExpiredError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (TokenInvalidError, AuthError):
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload


def require_auth(user: dict[str, Any] | None) -> dict[str, Any]:
    """Raise 401 if no authenticated user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(user: dict[str, Any], *allowed_roles: str) -> None:
    """Raise 403 if user role is not in *allowed_roles*."""
    if user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Resolve authenticated user (optional — unauthenticated allowed when bootstrap)
    user = await get_current_user(credentials)

    # ── Domain resolution: semantic routing → explicit → default ──
    routing_record: dict[str, Any] = {
        "event": "routing_decision",
        "explicit_domain": req.domain_id,
        "session_id": session_id,
        "timestamp": time.time(),
    }

    if req.domain_id:
        # Explicit domain_id — always wins
        try:
            resolved_domain_id = DOMAIN_REGISTRY.resolve_domain_id(req.domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        routing_record["method"] = "explicit"
        routing_record["confidence"] = 1.0
    else:
        # Semantic routing when no domain_id provided
        try:
            from core_nlp import classify_domain
        except ImportError:
            classify_domain = None  # type: ignore[assignment]

        routing_map = DOMAIN_REGISTRY.get_domain_routing_map()
        inferred = None

        if classify_domain is not None and routing_map:
            # Filter to accessible domains if user is authenticated
            accessible = None
            if user is not None:
                accessible = _get_accessible_domain_ids(user, routing_map)
            inferred = classify_domain(req.message, routing_map, accessible)

        if inferred is not None:
            resolved_domain_id = inferred["domain_id"]
            routing_record["method"] = inferred.get("method", "keyword")
            routing_record["confidence"] = inferred["confidence"]
            routing_record["inferred_domain"] = inferred["domain_id"]
            log.info(
                "[%s] Semantic routing: %s (confidence=%.3f, method=%s)",
                session_id,
                resolved_domain_id,
                inferred["confidence"],
                inferred.get("method"),
            )
        else:
            # Fall back to role-based default (or global default for unauthenticated users)
            try:
                resolved_domain_id = DOMAIN_REGISTRY.resolve_default_for_user(user)
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Could not determine domain. Please specify domain_id.",
                )
            routing_record["method"] = "role_default"
            routing_record["confidence"] = 0.0
            log.info(
                "[%s] Role-based default routing: %s (role=%s)",
                session_id,
                resolved_domain_id,
                user.get("role") if user else "unauthenticated",
            )

    routing_record["final_domain"] = resolved_domain_id

    # ── RBAC gate: check EXECUTE permission on the target domain ──
    if user is not None:
        runtime = DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)
        domain_physics_path = runtime["domain_physics_path"]
        domain = await run_in_threadpool(PERSISTENCE.load_domain_physics, str(domain_physics_path))
        module_perms = domain.get("permissions")
        if module_perms:
            has_access = check_permission(
                user_id=user["sub"],
                user_role=user["role"],
                module_permissions=module_perms,
                operation=Operation.EXECUTE,
            )
            if not has_access:
                raise HTTPException(status_code=403, detail="Module access denied")

    # ── Log routing decision to meta-ledger (Step 9) ─────────
    try:
        PERSISTENCE.append_log_record(
            session_id,
            routing_record,
            ledger_path=PERSISTENCE.get_log_ledger_path(session_id, domain_id="_meta"),
        )
    except Exception:
        log.debug("Could not write routing decision to meta-ledger")

    try:
        result = await run_in_threadpool(
            process_message,
            session_id,
            req.message,
            req.turn_data_override,
            req.deterministic_response,
            resolved_domain_id,
            user,
            req.model_id,
            req.model_version,
        )
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("Error processing message for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(
        session_id=session_id,
        response=result["response"],
        action=result["action"],
        prompt_type=result["prompt_type"],
        escalated=result["escalated"],
        tool_results=result.get("tool_results") or None,
        domain_id=result.get("domain_id"),
    )


def _get_accessible_domain_ids(
    user: dict[str, Any],
    routing_map: dict[str, dict[str, Any]],
) -> list[str]:
    """Return domain IDs the user has EXECUTE access to."""
    if user.get("role") == "root":
        return list(routing_map.keys())

    accessible: list[str] = []
    for domain_id in routing_map:
        try:
            runtime = DOMAIN_REGISTRY.get_runtime_context(domain_id)
            domain_physics_path = runtime["domain_physics_path"]
            domain = PERSISTENCE.load_domain_physics(str(domain_physics_path))
            module_perms = domain.get("permissions")
            if module_perms is None:
                # No permissions block = open access
                accessible.append(domain_id)
                continue
            if check_permission(
                user_id=user["sub"],
                user_role=user["role"],
                module_permissions=module_perms,
                operation=Operation.EXECUTE,
            ):
                accessible.append(domain_id)
        except Exception:
            continue
    return accessible


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": LLM_PROVIDER}


@app.get("/api/domains")
async def list_domains() -> list[dict[str, Any]]:
    """Return catalog of available domains for multi-domain deployments."""
    return DOMAIN_REGISTRY.list_domains()


@app.get("/api/domain-info")
async def domain_info(domain_id: str | None = None) -> dict[str, Any]:
    """Return domain UI manifest and identity for front-end theming."""
    try:
        resolved = DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics_path = runtime["domain_physics_path"]
    domain = PERSISTENCE.load_domain_physics(str(domain_physics_path))
    manifest = runtime.get("ui_manifest") or {}
    return {
        "domain_id": domain.get("id", "unknown"),
        "domain_version": domain.get("version", "unknown"),
        "ui_manifest": manifest,
    }


class ToolRequestWithDomain(BaseModel):
    payload: dict[str, Any]
    domain_id: str | None = None


@app.post("/api/tool/{tool_id}", response_model=ToolResponse)
async def run_tool(
    tool_id: str,
    req: ToolRequestWithDomain,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ToolResponse:
    try:
        resolved = DOMAIN_REGISTRY.resolve_domain_id(req.domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)

    # Tool invocation requires at least execute permission
    user = await get_current_user(credentials)
    if user is not None:
        domain_physics_path = runtime["domain_physics_path"]
        domain = await run_in_threadpool(PERSISTENCE.load_domain_physics, str(domain_physics_path))
        module_perms = domain.get("permissions")
        if module_perms and not check_permission(
            user_id=user["sub"],
            user_role=user["role"],
            module_permissions=module_perms,
            operation=Operation.EXECUTE,
        ):
            raise HTTPException(status_code=403, detail="Module access denied")
    try:
        result = await run_in_threadpool(invoke_runtime_tool, tool_id, req.payload, runtime)
    except Exception as exc:
        log.exception("Tool invocation failed for %s", tool_id)
        raise HTTPException(status_code=400, detail=str(exc))
    return ToolResponse(tool_id=tool_id, result=result)


@app.get("/api/system-log/validate", response_model=SystemLogValidateResponse)
async def validate_system_log(
    session_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> SystemLogValidateResponse:
    """Validate System Log hash-chain integrity for one session or all known sessions."""
    user = await get_current_user(credentials)
    if user is not None:
        require_role(user, "root", "domain_authority", "qa", "auditor")
    try:
        result = await run_in_threadpool(PERSISTENCE.validate_log_chain, session_id)
    except Exception as exc:
        log.exception("System Log validation failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return SystemLogValidateResponse(result=result)


# ─────────────────────────────────────────────────────────────
# Auth Endpoints
# ─────────────────────────────────────────────────────────────


@app.post("/api/auth/register", response_model=TokenResponse)
async def register(req: RegisterRequest) -> TokenResponse:
    """Register a new user.

    In bootstrap mode the first user is automatically assigned the ``root`` role.
    Non-bootstrap registration of privileged roles requires an authenticated root user.
    """
    if req.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {req.role}")

    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    existing = await run_in_threadpool(PERSISTENCE.get_user_by_username, req.username)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already taken")

    # Bootstrap: first user auto-promoted to root
    all_users = await run_in_threadpool(PERSISTENCE.list_users)
    role = req.role
    if BOOTSTRAP_MODE and len(all_users) == 0:
        role = "root"
        log.info("Bootstrap mode: first user promoted to root")

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(req.password)

    await run_in_threadpool(
        PERSISTENCE.create_user,
        user_id,
        req.username,
        pw_hash,
        role,
        req.governed_modules,
    )

    token = create_jwt(
        user_id=user_id,
        role=role,
        governed_modules=req.governed_modules or [],
    )

    log.info("Registered user %s (%s) with role %s", req.username, user_id, role)
    return TokenResponse(access_token=token, user_id=user_id, role=role)


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    """Authenticate and return a JWT."""
    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = await run_in_threadpool(PERSISTENCE.get_user_by_username, req.username)
    if user is None or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account deactivated")

    token = create_jwt(
        user_id=user["user_id"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
    )

    return TokenResponse(
        access_token=token,
        user_id=user["user_id"],
        role=user["role"],
    )


@app.get("/api/auth/guest-token", response_model=TokenResponse)
async def guest_token() -> TokenResponse:
    """Issue a short-lived JWT with the guest role.

    No credentials required.  The guest role has Level-4 access; actual
    module permissions are determined by each domain's ``guest_access``
    block in its domain-physics document.
    """
    guest_id = f"guest_{uuid.uuid4().hex[:12]}"
    token = create_jwt(
        user_id=guest_id,
        role="guest",
        governed_modules=[],
        ttl_minutes=30,
    )
    return TokenResponse(access_token=token, user_id=guest_id, role="guest")


@app.post("/api/auth/refresh", response_model=TokenResponse)
async def refresh(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenResponse:
    """Issue a fresh token for an authenticated user."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    # Re-read from persistence to get latest role/modules
    user = await run_in_threadpool(PERSISTENCE.get_user, user_data["sub"])
    if user is None or not user.get("active", True):
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    token = create_jwt(
        user_id=user["user_id"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
    )
    return TokenResponse(
        access_token=token,
        user_id=user["user_id"],
        role=user["role"],
    )


@app.get("/api/auth/me", response_model=UserResponse)
async def me(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserResponse:
    """Return the profile of the currently authenticated user."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    user = await run_in_threadpool(PERSISTENCE.get_user, user_data["sub"])
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"],
        governed_modules=user.get("governed_modules") or [],
        active=user.get("active", True),
    )


@app.get("/api/auth/users", response_model=list[UserResponse])
async def list_all_users(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[UserResponse]:
    """List all users (root and it_support only)."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root", "it_support")
    users = await run_in_threadpool(PERSISTENCE.list_users)
    return [
        UserResponse(
            user_id=u["user_id"],
            username=u["username"],
            role=u["role"],
            governed_modules=u.get("governed_modules") or [],
            active=u.get("active", True),
        )
        for u in users
    ]


# ─────────────────────────────────────────────────────────────
# Admin Endpoints — Phase 1: User & Access Management
# ─────────────────────────────────────────────────────────────


@app.patch("/api/auth/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserResponse:
    """Update user role and/or governed_modules (root only)."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root")

    if req.role is not None and req.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {req.role}")

    if req.governed_modules is not None and req.role != "domain_authority":
        if req.role is not None:
            raise HTTPException(
                status_code=400,
                detail="governed_modules can only be set for domain_authority role",
            )

    target = await run_in_threadpool(PERSISTENCE.get_user, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = target["role"]
    new_role = req.role or old_role
    new_governed = req.governed_modules if req.governed_modules is not None else target.get("governed_modules")

    updated = await run_in_threadpool(
        PERSISTENCE.update_user_role, user_id, new_role, new_governed
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")

    # System Log: TraceEvent for role change
    if new_role != old_role:
        event = build_trace_event(
            session_id="admin",
            actor_id=user_data["sub"],
            event_type="other",
            decision=f"role_change: {old_role} -> {new_role}",
            evidence_summary={
                "target_user_id": user_id,
                "old_role": old_role,
                "new_role": new_role,
            },
        )
        try:
            PERSISTENCE.append_log_record(
                "admin", event,
                ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
            )
        except Exception:
            log.debug("Could not write role_change trace event")

    return UserResponse(
        user_id=updated["user_id"],
        username=updated["username"],
        role=updated["role"],
        governed_modules=updated.get("governed_modules") or [],
        active=updated.get("active", True),
    )


@app.delete("/api/auth/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """Deactivate a user (soft delete). Root only."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root")

    if user_id == user_data["sub"]:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    success = await run_in_threadpool(PERSISTENCE.deactivate_user, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")

    event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="other",
        decision="user_deactivated",
        evidence_summary={"target_user_id": user_id},
    )
    try:
        PERSISTENCE.append_log_record(
            "admin", event,
            ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write user_deactivated trace event")


@app.post("/api/auth/revoke", status_code=200)
async def revoke_token(
    req: RevokeRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, str]:
    """Revoke an auth token. Root/it_support for any user; authenticated user for own token."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if req.user_id is not None and req.user_id != user_data["sub"]:
        require_role(user_data, "root", "it_support")

    # Revoke the current token's JTI
    jti = user_data.get("jti")
    if jti:
        revoke_token_jti(jti)

    event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="other",
        decision="token_revoked",
        evidence_summary={"target_user_id": req.user_id or user_data["sub"]},
    )
    try:
        PERSISTENCE.append_log_record(
            "admin", event,
            ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write token_revoked trace event")

    return {"status": "revoked"}


@app.post("/api/auth/password-reset", status_code=200)
async def password_reset(
    req: PasswordResetRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, str]:
    """Reset password. Root/it_support for any user; authenticated user for own."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    target_user_id = req.user_id or user_data["sub"]
    if target_user_id != user_data["sub"]:
        require_role(user_data, "root", "it_support")

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    new_hash = hash_password(req.new_password)
    success = await run_in_threadpool(PERSISTENCE.update_user_password, target_user_id, new_hash)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")

    event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="other",
        decision="password_reset",
        evidence_summary={"target_user_id": target_user_id},
    )
    try:
        PERSISTENCE.append_log_record(
            "admin", event,
            ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write password_reset trace event")

    return {"status": "password_updated"}


# ─────────────────────────────────────────────────────────────
# Admin Endpoints — Phase 2: Domain Pack Lifecycle
# ─────────────────────────────────────────────────────────────


@app.post("/api/domain-pack/commit")
async def domain_pack_commit(
    req: DomainCommitRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Commit domain pack hash to System Log."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, req.domain_id):
        raise HTTPException(status_code=403, detail="Not authorized for this domain")

    try:
        resolved = DOMAIN_REGISTRY.resolve_domain_id(req.domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics_path = runtime["domain_physics_path"]
    domain = await run_in_threadpool(PERSISTENCE.load_domain_physics, str(domain_physics_path))

    subject_hash = admin_canonical_sha256(domain)
    subject_version = str(domain.get("version", ""))
    subject_id = str(domain.get("id", resolved))

    record = build_commitment_record(
        actor_id=req.actor_id or user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="domain_pack_activation",
        subject_id=subject_id,
        summary=req.summary or f"Domain pack activation: {resolved}",
        subject_version=subject_version,
        subject_hash=subject_hash,
    )

    PERSISTENCE.append_log_record(
        "admin", record,
        ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id=resolved),
    )

    return {
        "record_id": record["record_id"],
        "subject_hash": subject_hash,
        "subject_version": subject_version,
        "commitment_type": "domain_pack_activation",
    }


@app.get("/api/domain-pack/{domain_id}/history")
async def domain_pack_history(
    domain_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    """List version/commitment history for a domain pack."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority" and can_govern_domain(user_data, domain_id):
            pass  # allowed
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(PERSISTENCE.query_commitments, domain_id)
    return [
        {
            "record_id": r.get("record_id"),
            "commitment_type": r.get("commitment_type"),
            "timestamp": r.get("timestamp_utc"),
            "subject_version": r.get("subject_version"),
            "subject_hash": r.get("subject_hash"),
            "summary": r.get("summary"),
        }
        for r in records
    ]


@app.patch("/api/domain-pack/{domain_id}/physics")
async def update_domain_physics(
    domain_id: str,
    req: DomainPhysicsUpdateRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Update domain physics fields and auto-commit."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, domain_id):
        raise HTTPException(status_code=403, detail="Not authorized for this domain")

    try:
        resolved = DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics_path = Path(runtime["domain_physics_path"])

    # Load, update, write atomically
    domain = await run_in_threadpool(PERSISTENCE.load_domain_physics, str(domain_physics_path))
    for key, value in req.updates.items():
        domain[key] = value

    def _write_physics() -> None:
        tmp = domain_physics_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(domain, fh, indent=2, ensure_ascii=False)
        tmp.replace(domain_physics_path)

    await run_in_threadpool(_write_physics)

    subject_hash = admin_canonical_sha256(domain)
    subject_id = str(domain.get("id", resolved))

    # Auto-commit
    record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="domain_pack_activation",
        subject_id=subject_id,
        summary=req.summary,
        subject_version=str(domain.get("version", "")),
        subject_hash=subject_hash,
        metadata={"updated_fields": list(req.updates.keys())},
    )
    PERSISTENCE.append_log_record(
        "admin", record,
        ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id=resolved),
    )

    return {
        "subject_hash": subject_hash,
        "updated_fields": list(req.updates.keys()),
        "record_id": record["record_id"],
    }


def _close_session(session_id: str, actor_id: str, actor_role: str, close_type: str = "normal", close_reason: str | None = None) -> None:
    """Close a session: write CommitmentRecords and remove from memory."""
    container = _session_containers.get(session_id)
    if container is None:
        return

    for did, ctx in container.contexts.items():
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
            PERSISTENCE.append_log_record(
                session_id, record,
                ledger_path=PERSISTENCE.get_log_ledger_path(session_id, domain_id=did),
            )
        except Exception:
            log.debug("Could not write session_close record for %s/%s", session_id, did)

    # Persist final state then free memory
    _persist_session_container(session_id, container)
    del _session_containers[session_id]


@app.post("/api/session/{session_id}/close", status_code=200)
async def close_session(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, str]:
    """Explicitly close a session."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    container = _session_containers.get(session_id)
    if container is None:
        raise HTTPException(status_code=404, detail="Session not found or already closed")

    # Access check: root, it_support, governed domain_authority, or session owner
    is_owner = container.user is not None and container.user.get("sub") == user_data["sub"]
    is_privileged = user_data["role"] in ("root", "it_support")
    is_da = user_data["role"] == "domain_authority" and can_govern_domain(
        user_data, container.active_domain_id
    )
    if not (is_owner or is_privileged or is_da):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    await run_in_threadpool(
        _close_session,
        session_id,
        user_data["sub"],
        map_role_to_actor_role(user_data["role"]),
        "normal",
    )
    return {"status": "closed", "session_id": session_id}


# ─────────────────────────────────────────────────────────────
# Ingestion Endpoints
# ─────────────────────────────────────────────────────────────

# Lazy singleton — created on first use so config is loaded first.
_INGEST_SERVICE: Any = None


def _get_ingest_service() -> Any:
    global _INGEST_SERVICE
    if _INGEST_SERVICE is None:
        from lumina.ingestion.service import IngestService

        _INGEST_SERVICE = IngestService(
            persistence_append=lambda sid, rec: PERSISTENCE.append_log_record(
                sid, rec,
                ledger_path=PERSISTENCE.get_log_ledger_path(sid, domain_id="_admin"),
            ),
            max_file_size_mb=10,
        )
    return _INGEST_SERVICE


@app.post("/api/ingest/upload")
async def ingest_upload(
    file: UploadFile,
    domain_id: str = Form(...),
    module_id: str | None = Form(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Upload a document for ingestion into a domain module.

    Requires ``ingest`` permission on the target module.
    """
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    # RBAC: check ingest permission
    try:
        resolved = DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics = await run_in_threadpool(
        PERSISTENCE.load_domain_physics, runtime["domain_physics_path"]
    )
    perms = domain_physics.get("permissions", {})
    perms["guest_access"] = domain_physics.get("guest_access")

    if user_data["role"] != "root":
        from lumina.core.permissions import Operation as PermOp, check_permission
        if not check_permission(user_data["sub"], user_data["role"], perms, PermOp.INGEST):
            raise HTTPException(status_code=403, detail="Ingest permission required")

    # Detect content type from filename
    filename = file.filename or "unknown"
    content_type = _detect_content_type(filename)
    if content_type is None:
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {filename}")

    file_bytes = await file.read()
    svc = _get_ingest_service()

    try:
        doc_id = svc.accept_document(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            actor_id=user_data["sub"],
            domain_id=resolved,
            module_id=module_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ingestion_id": doc_id, "status": "pending_extraction", "domain_id": resolved}


@app.get("/api/ingest/{ingestion_id}")
async def get_ingestion(
    ingestion_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Retrieve an IngestionRecord with its interpretations."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    svc = _get_ingest_service()
    record = svc.get_record(ingestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion not found")

    # RBAC: any authenticated user with read on the domain can see the record
    return record


@app.post("/api/ingest/{ingestion_id}/extract")
async def ingest_extract(
    ingestion_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Trigger SLM extraction for an ingestion.

    Returns immediately with the current status; extraction may still
    be in progress for large documents.
    """
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    svc = _get_ingest_service()
    record = svc.get_record(ingestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion not found")

    domain_id = record.get("domain_id", "")
    try:
        resolved = DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics = await run_in_threadpool(
        PERSISTENCE.load_domain_physics, runtime["domain_physics_path"]
    )

    ingestion_config = domain_physics.get("ingestion_config") or {}
    max_interps = ingestion_config.get("max_interpretations", 3)

    interpretations = await run_in_threadpool(
        svc.extract_interpretations,
        ingestion_id,
        domain_physics,
        domain_physics.get("glossary"),
        None,
        max_interps,
    )

    return {
        "ingestion_id": ingestion_id,
        "status": "extraction_complete",
        "interpretation_count": len(interpretations),
        "interpretations": interpretations,
    }


@app.post("/api/ingest/{ingestion_id}/review")
async def ingest_review(
    ingestion_id: str,
    req: dict[str, Any] = Body(...),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Submit a review decision for an ingestion.

    Body: ``{decision, selected_interpretation_id?, edits?, review_notes?}``
    Requires ``domain_authority`` on the governed module.
    """
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Domain authority required")

    svc = _get_ingest_service()
    record = svc.get_record(ingestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion not found")

    if user_data["role"] == "domain_authority":
        if not can_govern_domain(user_data, record.get("domain_id", "")):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")

    decision = req.get("decision", "")
    if decision not in ("approve", "reject", "edit"):
        raise HTTPException(status_code=400, detail="decision must be approve, reject, or edit")

    try:
        updated = svc.review_interpretation(
            ingestion_id=ingestion_id,
            decision=decision,
            reviewer_id=user_data["sub"],
            selected_interpretation_id=req.get("selected_interpretation_id"),
            edits=req.get("edits"),
            review_notes=req.get("review_notes"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return updated


@app.post("/api/ingest/{ingestion_id}/commit")
async def ingest_commit(
    ingestion_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Finalize and System Log-commit an approved ingestion."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Domain authority required")

    svc = _get_ingest_service()
    record = svc.get_record(ingestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion not found")

    if user_data["role"] == "domain_authority":
        if not can_govern_domain(user_data, record.get("domain_id", "")):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")

    try:
        result = svc.commit_ingestion(ingestion_id, user_data["sub"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return result


@app.get("/api/ingest")
async def list_ingestions(
    domain_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    """List ingestion records with optional filters."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    svc = _get_ingest_service()
    records = svc.list_records(domain_id=domain_id, status=status, limit=limit, offset=offset)

    # Scope DA to governed domains
    if user_data["role"] == "domain_authority":
        governed = user_data.get("governed_modules") or []
        records = [r for r in records if r.get("domain_id") in governed]

    return records


def _detect_content_type(filename: str) -> str | None:
    """Map filename extension to ingestion content type."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "pdf": "pdf",
        "docx": "docx",
        "doc": "docx",
        "md": "markdown",
        "markdown": "markdown",
        "txt": "markdown",
        "csv": "csv",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
    }.get(ext)


# ─────────────────────────────────────────────────────────────
# Dashboard Endpoints
# ─────────────────────────────────────────────────────────────


@app.get("/api/dashboard/domains")
async def dashboard_domains(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    """List domains visible to the current user with summary stats."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Dashboard requires DA or root role")

    all_domains = DOMAIN_REGISTRY.list_domains()

    # Scope DA to governed domains
    if user_data["role"] == "domain_authority":
        governed = set(user_data.get("governed_modules") or [])
        all_domains = [d for d in all_domains if d.get("domain_id") in governed]

    results: list[dict[str, Any]] = []
    for domain in all_domains:
        domain_id = domain.get("domain_id", "")
        # Escalation count for domain
        try:
            escalations = await run_in_threadpool(
                PERSISTENCE.query_escalations,
                domain_id=domain_id,
                status="pending",
            )
            pending_escalations = len(escalations)
        except Exception:
            pending_escalations = 0

        # Ingestion count
        svc = _get_ingest_service()
        pending_ingestions = len(svc.list_records(domain_id=domain_id, status="pending_extraction"))
        review_ingestions = len(svc.list_records(domain_id=domain_id, status="extraction_complete"))

        results.append({
            "domain_id": domain_id,
            "name": domain.get("name", domain_id),
            "version": domain.get("version", "0.0.0"),
            "pending_escalations": pending_escalations,
            "pending_ingestions": pending_ingestions,
            "review_ingestions": review_ingestions,
        })

    return results


@app.get("/api/dashboard/telemetry")
async def dashboard_telemetry(
    domain_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Aggregate telemetry summary for the dashboard."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Dashboard requires DA or root role")

    # Query recent System Log records for stats
    records = await run_in_threadpool(
        PERSISTENCE.query_log_records,
        domain_id=domain_id,
    )

    record_types: dict[str, int] = {}
    for r in records:
        rt = r.get("record_type", "unknown")
        record_types[rt] = record_types.get(rt, 0) + 1

    # Escalation summary
    try:
        escalations = await run_in_threadpool(
            PERSISTENCE.query_escalations,
            domain_id=domain_id,
        )
    except Exception:
        escalations = []

    pending = sum(1 for e in escalations if e.get("status") == "pending")
    resolved = sum(1 for e in escalations if e.get("status") == "resolved")

    return {
        "total_log_records": len(records),
        "record_type_counts": record_types,
        "escalation_summary": {
            "total": len(escalations),
            "pending": pending,
            "resolved": resolved,
        },
        "domain_filter": domain_id,
    }


# ─────────────────────────────────────────────────────────────
# Night Cycle endpoints
# ─────────────────────────────────────────────────────────────

_NIGHT_SCHEDULER: Any = None


def _get_night_scheduler() -> Any:
    global _NIGHT_SCHEDULER
    if _NIGHT_SCHEDULER is None:
        from lumina.nightcycle.scheduler import NightCycleScheduler

        nc_cfg: dict[str, Any] = {}
        try:
            rt = load_yaml(Path("cfg/system-runtime-config.yaml"))
            nc_cfg = rt.get("night_cycle", {})
        except Exception:
            pass
        _NIGHT_SCHEDULER = NightCycleScheduler(config=nc_cfg, persistence=PERSISTENCE)
    return _NIGHT_SCHEDULER


@app.post("/api/nightcycle/trigger")
async def nightcycle_trigger(
    req: dict[str, Any] = Body(default={}),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Manually trigger a night cycle run."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    scheduler = _get_night_scheduler()
    task_names = req.get("tasks")
    domain_ids = req.get("domain_ids")
    run_id = scheduler.trigger_async(
        actor_id=user_data["sub"],
        task_names=task_names,
        domain_ids=domain_ids,
    )
    return {"run_id": run_id, "status": "started"}


@app.get("/api/nightcycle/status")
async def nightcycle_status(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Get current night cycle status."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority", "auditor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return _get_night_scheduler().get_status()


@app.get("/api/nightcycle/report/{run_id}")
async def nightcycle_report(
    run_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Get detailed night cycle report."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    report = _get_night_scheduler().get_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@app.get("/api/nightcycle/proposals")
async def nightcycle_proposals(
    domain_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    """List pending night cycle proposals."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return _get_night_scheduler().get_pending_proposals(domain_id=domain_id)


@app.post("/api/nightcycle/proposals/{proposal_id}/resolve")
async def nightcycle_resolve_proposal(
    proposal_id: str,
    req: dict[str, Any] = Body(...),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Approve or reject a night cycle proposal."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    action = req.get("action")
    if action not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="action must be 'approved' or 'rejected'")

    found = _get_night_scheduler().resolve_proposal(proposal_id, action)
    if not found:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"proposal_id": proposal_id, "status": action}


# ─────────────────────────────────────────────────────────────
# Admin Endpoints — Phase 3: Audit & Escalation
# ─────────────────────────────────────────────────────────────


@app.get("/api/escalations")
async def list_escalations(
    status: str | None = None,
    domain_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    """List escalation records with optional filters."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "it_support", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority":
            pass  # will be filtered by governed domains below
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(
        PERSISTENCE.query_escalations,
        status=status,
        domain_id=domain_id,
        limit=limit,
        offset=offset,
    )

    # Scope domain_authority to governed domains only
    if user_data["role"] == "domain_authority":
        governed = user_data.get("governed_modules") or []
        records = [r for r in records if r.get("domain_pack_id") in governed]

    return records


@app.post("/api/escalations/{escalation_id}/resolve")
async def resolve_escalation(
    escalation_id: str,
    req: EscalationResolveRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Resolve an escalation."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if req.decision not in ("approve", "reject", "defer"):
        raise HTTPException(status_code=400, detail="decision must be approve, reject, or defer")

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Find the escalation record
    all_escalations = await run_in_threadpool(PERSISTENCE.query_escalations)
    target = None
    for esc in all_escalations:
        if esc.get("record_id") == escalation_id:
            target = esc
            break

    if target is None:
        raise HTTPException(status_code=404, detail="Escalation not found")

    # Domain authority scoping
    if user_data["role"] == "domain_authority":
        domain = target.get("domain_pack_id", "")
        if not can_govern_domain(user_data, domain):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")

    record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="escalation_resolution",
        subject_id=escalation_id,
        summary=f"Escalation {req.decision}: {req.reasoning[:200]}",
        metadata={
            "decision": req.decision,
            "reasoning": req.reasoning,
            "original_trigger": target.get("trigger", ""),
        },
        references=[escalation_id],
    )

    session_id = target.get("session_id", "admin")
    PERSISTENCE.append_log_record(
        session_id, record,
        ledger_path=PERSISTENCE.get_log_ledger_path(session_id, domain_id="_admin"),
    )

    return {
        "record_id": record["record_id"],
        "escalation_id": escalation_id,
        "decision": req.decision,
    }


@app.get("/api/audit/log")
async def audit_log(
    session_id: str | None = None,
    domain_id: str | None = None,
    format: str = "json",
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Generate audit log report from System Logs records."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    # RBAC: root=all, da=governed, qa/auditor=scoped, user=own sessions only
    allowed_roles = ("root", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority":
            pass  # filtered below
        elif user_data["role"] == "user":
            pass  # filtered to own sessions below
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(
        PERSISTENCE.query_log_records,
        session_id=session_id,
        domain_id=domain_id,
    )

    # Log the audit request itself
    audit_event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="audit_requested",
        decision=f"Audit log requested: session={session_id}, domain={domain_id}",
    )
    try:
        PERSISTENCE.append_log_record(
            "admin", audit_event,
            ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write audit_requested trace event")

    # Build summary
    record_types: dict[str, int] = {}
    for r in records:
        rt = r.get("record_type", "unknown")
        record_types[rt] = record_types.get(rt, 0) + 1

    return {
        "total_records": len(records),
        "record_type_counts": record_types,
        "filters": {
            "session_id": session_id,
            "domain_id": domain_id,
        },
        "records": records if format == "json" else [],
        "generated_by": user_data["sub"],
    }


@app.get("/api/manifest/check", response_model=ManifestCheckResponse)
async def manifest_check(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ManifestCheckResponse:
    """Verify SHA-256 hashes for all artifacts in docs/MANIFEST.yaml.

    Accessible to: ``root``, ``domain_authority``, ``qa``, ``auditor``.
    Returns a structured integrity report; does not modify any files.
    """
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root", "domain_authority", "qa", "auditor")
    try:
        report = await run_in_threadpool(check_manifest_report, _REPO_ROOT)
    except Exception as exc:
        log.exception("Manifest integrity check failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return ManifestCheckResponse(**report)


@app.post("/api/manifest/regen", response_model=ManifestRegenResponse)
async def manifest_regen(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ManifestRegenResponse:
    """Recompute and rewrite SHA-256 hashes in docs/MANIFEST.yaml.

    Restricted to: ``root`` and ``domain_authority`` only.
    Writes a System Log TraceEvent for the audit trail.
    """
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root", "domain_authority")
    try:
        report = await run_in_threadpool(regen_manifest_report, _REPO_ROOT)
    except Exception as exc:
        log.exception("Manifest regen failed")
        raise HTTPException(status_code=500, detail=str(exc))

    # Write audit trail event
    event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="other",
        decision=f"manifest_regen: updated {report['updated_count']} artifact(s)",
        evidence_summary={
            "updated_count": report["updated_count"],
            "missing_paths": report["missing_paths"],
            "actor_role": user_data["role"],
        },
    )
    try:
        PERSISTENCE.append_log_record(
            "admin", event,
            ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write manifest_regen trace event")

    return ManifestRegenResponse(**report)


@app.get("/api/system-log/records")
async def query_log_records(
    session_id: str | None = None,
    record_type: str | None = None,
    event_type: str | None = None,
    domain_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    """Query System Log records with filters."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority":
            pass  # governed scope applies via domain_id filter
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(
        PERSISTENCE.query_log_records,
        session_id=session_id,
        record_type=record_type,
        event_type=event_type,
        domain_id=domain_id,
        limit=limit,
        offset=offset,
    )
    return records


@app.get("/api/system-log/sessions")
async def list_log_sessions(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    """List all System Log session IDs with summary info."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "domain_authority", "it_support", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    summaries = await run_in_threadpool(PERSISTENCE.list_log_sessions_summary)
    return summaries


@app.get("/api/system-log/records/{record_id}")
async def get_log_record(
    record_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Get a specific System Log record by record_id."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority":
            pass
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Search all records for the matching record_id
    all_records = await run_in_threadpool(PERSISTENCE.query_log_records, limit=10000)
    for r in all_records:
        if r.get("record_id") == record_id:
            return r

    raise HTTPException(status_code=404, detail="Record not found")


# ─────────────────────────────────────────────────────────────
# Admin Command Translation (SLM-powered, HITL-gated)
# ─────────────────────────────────────────────────────────────

# All operations the SLM may produce; unknown operations are rejected at stage time.
_KNOWN_OPERATIONS: frozenset[str] = frozenset({
    "update_domain_physics",
    "commit_domain_physics",
    "update_user_role",
    "deactivate_user",
    "resolve_escalation",
    "list_ingestions",
    "review_ingestion",
    "approve_interpretation",
    "reject_ingestion",
    "list_escalations",
    "explain_reasoning",
    "module_status",
    "trigger_night_cycle",
    "night_cycle_status",
    "review_proposals",
})


async def _execute_admin_operation(
    user_data: dict[str, Any],
    parsed: dict[str, Any],
    original_instruction: str,
) -> dict[str, Any]:
    """Execute a pre-validated, human-approved admin operation.

    RBAC is fully enforced here; caller must have already resolved the staged
    command via the /resolve endpoint.
    """
    operation = parsed["operation"]
    params = parsed.get("params") or {}
    result: dict[str, Any]

    if operation == "update_domain_physics":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        updates = params.get("updates") or {}
        if not domain_id or not updates:
            raise HTTPException(status_code=422, detail="domain_id and updates required")
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, domain_id):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
        try:
            resolved = DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)
        domain_physics_path = Path(runtime["domain_physics_path"])
        domain = await run_in_threadpool(PERSISTENCE.load_domain_physics, str(domain_physics_path))
        for k, v in updates.items():
            domain[k] = v

        def _write() -> None:
            tmp = domain_physics_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(domain, fh, indent=2, ensure_ascii=False)
            tmp.replace(domain_physics_path)

        await run_in_threadpool(_write)
        subject_hash = admin_canonical_sha256(domain)
        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(user_data["role"]),
            commitment_type="domain_pack_activation",
            subject_id=str(domain.get("id", resolved)),
            summary=f"SLM command: {original_instruction}",
            subject_version=str(domain.get("version", "")),
            subject_hash=subject_hash,
            metadata={"slm_command_translation": True, "updated_fields": list(updates.keys())},
        )
        PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id=resolved),
        )
        result = {"operation": operation, "subject_hash": subject_hash, "record_id": record["record_id"]}

    elif operation == "commit_domain_physics":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        if not domain_id:
            raise HTTPException(status_code=422, detail="domain_id required")
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, domain_id):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
        try:
            resolved = DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)
        domain_physics_path = Path(runtime["domain_physics_path"])
        domain = await run_in_threadpool(PERSISTENCE.load_domain_physics, str(domain_physics_path))
        subject_hash = admin_canonical_sha256(domain)
        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(user_data["role"]),
            commitment_type="domain_pack_activation",
            subject_id=str(domain.get("id", resolved)),
            summary=f"SLM command: {original_instruction}",
            subject_version=str(domain.get("version", "")),
            subject_hash=subject_hash,
            metadata={"slm_command_translation": True},
        )
        PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=PERSISTENCE.get_log_ledger_path("admin", domain_id=resolved),
        )
        result = {"operation": operation, "subject_hash": subject_hash, "record_id": record["record_id"]}

    elif operation == "update_user_role":
        if user_data["role"] != "root":
            raise HTTPException(status_code=403, detail="Only root can update user roles")
        target_user_id = str(params.get("user_id", parsed.get("target", "")))
        new_role = str(params.get("new_role", ""))
        if not target_user_id or new_role not in VALID_ROLES:
            raise HTTPException(status_code=422, detail="user_id and valid new_role required")
        await run_in_threadpool(PERSISTENCE.update_user_role, target_user_id, new_role)
        result = {"operation": operation, "user_id": target_user_id, "new_role": new_role}

    elif operation == "deactivate_user":
        if user_data["role"] != "root":
            raise HTTPException(status_code=403, detail="Only root can deactivate users")
        target_user_id = str(params.get("user_id", parsed.get("target", "")))
        if not target_user_id:
            raise HTTPException(status_code=422, detail="user_id required")
        if target_user_id == user_data["sub"]:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        await run_in_threadpool(PERSISTENCE.deactivate_user, target_user_id)
        result = {"operation": operation, "user_id": target_user_id}

    elif operation == "resolve_escalation":
        esc_id = str(params.get("escalation_id", parsed.get("target", "")))
        resolution = str(params.get("resolution", ""))
        rationale = str(params.get("rationale", ""))
        if not esc_id or resolution not in ("approved", "rejected", "deferred"):
            raise HTTPException(status_code=422, detail="escalation_id and valid resolution required")
        result = {"operation": operation, "escalation_id": esc_id, "resolution": resolution, "rationale": rationale}

    elif operation == "list_ingestions":
        domain_id = str(params.get("domain_id", "")) or None
        status_filter = str(params.get("status", "")) or None
        svc = _get_ingest_service()
        records = svc.list_records(domain_id=domain_id, status=status_filter, limit=20)
        if user_data["role"] == "domain_authority":
            governed = user_data.get("governed_modules") or []
            records = [r for r in records if r.get("domain_id") in governed]
        result = {"operation": operation, "count": len(records), "records": records}

    elif operation == "review_ingestion":
        ingestion_id = str(params.get("ingestion_id", parsed.get("target", "")))
        if not ingestion_id:
            raise HTTPException(status_code=422, detail="ingestion_id required")
        svc = _get_ingest_service()
        record = svc.get_record(ingestion_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Ingestion not found")
        result = {"operation": operation, "record": record}

    elif operation == "approve_interpretation":
        ingestion_id = str(params.get("ingestion_id", parsed.get("target", "")))
        interp_id = str(params.get("interpretation_id", ""))
        if not ingestion_id or not interp_id:
            raise HTTPException(status_code=422, detail="ingestion_id and interpretation_id required")
        if user_data["role"] not in ("root", "domain_authority"):
            raise HTTPException(status_code=403, detail="Domain authority required")
        svc = _get_ingest_service()
        try:
            updated = svc.review_interpretation(
                ingestion_id, decision="approve", reviewer_id=user_data["sub"],
                selected_interpretation_id=interp_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        result = {"operation": operation, "status": updated["status"], "ingestion_id": ingestion_id}

    elif operation == "reject_ingestion":
        ingestion_id = str(params.get("ingestion_id", parsed.get("target", "")))
        reason = str(params.get("reason", params.get("rationale", "")))
        if not ingestion_id:
            raise HTTPException(status_code=422, detail="ingestion_id required")
        if user_data["role"] not in ("root", "domain_authority"):
            raise HTTPException(status_code=403, detail="Domain authority required")
        svc = _get_ingest_service()
        try:
            updated = svc.review_interpretation(
                ingestion_id, decision="reject", reviewer_id=user_data["sub"],
                review_notes=reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        result = {"operation": operation, "status": updated["status"], "ingestion_id": ingestion_id}

    elif operation == "list_escalations":
        domain_id = str(params.get("domain_id", "")) or None
        escalations = await run_in_threadpool(
            PERSISTENCE.query_escalations,
            domain_id=domain_id,
            status="pending",
        )
        if user_data["role"] == "domain_authority":
            governed = user_data.get("governed_modules") or []
            escalations = [e for e in escalations if e.get("domain_pack_id") in governed]
        result = {"operation": operation, "count": len(escalations), "escalations": escalations}

    elif operation == "explain_reasoning":
        event_id = str(params.get("event_id", parsed.get("target", "")))
        if not event_id:
            raise HTTPException(status_code=422, detail="event_id required")
        records = await run_in_threadpool(PERSISTENCE.query_log_records)
        target = [r for r in records if r.get("record_id") == event_id]
        if not target:
            raise HTTPException(status_code=404, detail="System Log record not found")
        result = {"operation": operation, "record": target[0]}

    elif operation == "module_status":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        if not domain_id:
            raise HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)
        domain = await run_in_threadpool(
            PERSISTENCE.load_domain_physics, runtime["domain_physics_path"]
        )
        result = {
            "operation": operation,
            "domain_id": resolved,
            "version": domain.get("version"),
            "modules": [m.get("module_id") for m in (domain.get("modules") or [])],
        }

    elif operation in ("trigger_night_cycle", "night_cycle_status", "review_proposals"):
        scheduler = _get_night_scheduler()
        if operation == "trigger_night_cycle":
            if user_data["role"] not in ("root", "domain_authority"):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            run_id = scheduler.trigger_async(actor_id=user_data["sub"])
            result = {"operation": operation, "run_id": run_id, "status": "started"}
        elif operation == "night_cycle_status":
            result = scheduler.get_status()
            result["operation"] = operation
        else:  # review_proposals
            resolved_id = str(params.get("domain_id", parsed.get("target", "")))
            proposals = scheduler.get_pending_proposals(domain_id=resolved_id)
            result = {"operation": operation, "proposals": proposals, "count": len(proposals)}

    else:
        raise HTTPException(status_code=422, detail=f"Unknown operation: {operation}")

    return result


@app.post("/api/admin/command")
async def admin_command(
    req: AdminCommandRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Stage a natural-language admin instruction for human review.

    The SLM parses the instruction into a structured command and stores it
    in the staging store.  Nothing is executed.  The caller receives a
    ``staged_id`` that must be passed to ``POST /api/admin/command/{staged_id}/resolve``
    together with an Accept / Reject / Modify decision before any action occurs.

    Returns 422 if the SLM cannot parse the instruction or the operation is unknown.
    """
    _purge_expired_staged_commands()

    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority", "it_support"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if not slm_available():
        raise HTTPException(status_code=503, detail="SLM service unavailable")

    parsed = slm_parse_admin_command(req.instruction)
    if parsed is None:
        raise HTTPException(status_code=422, detail="Could not interpret command")

    operation = parsed.get("operation", "")
    if operation not in _KNOWN_OPERATIONS:
        raise HTTPException(status_code=422, detail=f"Unknown operation: {operation}")

    staged_id = str(uuid.uuid4())
    expires_at = time.time() + _STAGED_CMD_TTL_SECONDS

    # Write the "staged" System Log record immediately so even rejected commands are auditable.
    stage_record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="hitl_command_staged",
        subject_id=staged_id,
        summary=f"HITL staged: {req.instruction[:200]}",
        subject_version=None,
        subject_hash=None,
        metadata={
            "staged_id": staged_id,
            "parsed_command": parsed,
            "original_instruction": req.instruction,
        },
    )
    PERSISTENCE.append_log_record(
        "admin", stage_record,
        ledger_path=PERSISTENCE.get_log_ledger_path("admin"),
    )

    entry: dict[str, Any] = {
        "staged_id": staged_id,
        "actor_id": user_data["sub"],
        "actor_role": user_data["role"],
        "parsed_command": parsed,
        "original_instruction": req.instruction,
        "staged_at": time.time(),
        "expires_at": expires_at,
        "log_stage_record_id": stage_record["record_id"],
        "resolved": False,
    }
    with _STAGED_COMMANDS_LOCK:
        _STAGED_COMMANDS[staged_id] = entry

    return {
        "staged_id": staged_id,
        "staged_command": parsed,
        "original_instruction": req.instruction,
        "expires_at": expires_at,
        "log_stage_record_id": stage_record["record_id"],
    }


@app.post("/api/admin/command/{staged_id}/resolve")
async def admin_command_resolve(
    staged_id: str,
    req: CommandResolveRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Human resolution gate for a staged admin command.

    ``action`` must be one of:
    - ``"accept"``  — execute the command exactly as the SLM parsed it.
    - ``"reject"``  — discard the command; nothing is executed.
    - ``"modify"``  — replace the parsed schema with ``modified_schema``, then execute.

    Only the original actor may resolve their own staged commands, **except** that
    ``root`` may resolve any staged command regardless of who staged it.

    Each resolution path writes its own System Log record (``hitl_command_accepted``,
    ``hitl_command_rejected``, or ``hitl_command_modified``).
    """
    # Note: do NOT call _purge_expired_staged_commands() here — we need the entry
    # to still be present so we can return 410 rather than 404 for expired commands.

    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority", "it_support"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if req.action not in _HITL_VALID_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action '{req.action}'. Must be one of: accept, reject, modify",
        )

    with _STAGED_COMMANDS_LOCK:
        entry = _STAGED_COMMANDS.get(staged_id)

    if entry is None:
        raise HTTPException(status_code=404, detail="Staged command not found")

    if entry["expires_at"] < time.time():
        with _STAGED_COMMANDS_LOCK:
            _STAGED_COMMANDS.pop(staged_id, None)
        raise HTTPException(status_code=410, detail="Staged command has expired")

    if entry["resolved"]:
        raise HTTPException(status_code=409, detail="Staged command has already been resolved")

    # Ownership check: only the original actor or root may resolve.
    if user_data["role"] != "root" and entry["actor_id"] != user_data["sub"]:
        raise HTTPException(status_code=403, detail="Not authorized to resolve this staged command")

    # Mark consumed immediately to prevent double-resolution (optimistic under the lock).
    with _STAGED_COMMANDS_LOCK:
        if _STAGED_COMMANDS.get(staged_id, {}).get("resolved"):
            raise HTTPException(status_code=409, detail="Staged command has already been resolved")
        _STAGED_COMMANDS[staged_id]["resolved"] = True

    actor_role = map_role_to_actor_role(user_data["role"])
    parsed = entry["parsed_command"]
    original_instruction = entry["original_instruction"]

    if req.action == "reject":
        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=actor_role,
            commitment_type="hitl_command_rejected",
            subject_id=staged_id,
            summary=f"HITL rejected: {original_instruction[:200]}",
            subject_version=None,
            subject_hash=None,
            metadata={
                "staged_id": staged_id,
                "log_stage_record_id": entry["log_stage_record_id"],
                "parsed_command": parsed,
            },
        )
        PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=PERSISTENCE.get_log_ledger_path("admin"),
        )
        return {
            "staged_id": staged_id,
            "action": "reject",
            "log_record_id": record["record_id"],
        }

    if req.action == "modify":
        if not req.modified_schema or not isinstance(req.modified_schema, dict):
            raise HTTPException(status_code=422, detail="modified_schema is required for 'modify' action")
        modified_op = req.modified_schema.get("operation", "")
        if modified_op not in _KNOWN_OPERATIONS:
            raise HTTPException(status_code=422, detail=f"Unknown operation in modified_schema: {modified_op}")
        delta = _compute_schema_delta(parsed, req.modified_schema)
        parsed = req.modified_schema
        commitment_type: str = "hitl_command_modified"
        metadata: dict[str, Any] = {
            "staged_id": staged_id,
            "log_stage_record_id": entry["log_stage_record_id"],
            "delta": delta,
            "modified_schema": parsed,
        }
    else:  # accept
        commitment_type = "hitl_command_accepted"
        metadata = {
            "staged_id": staged_id,
            "log_stage_record_id": entry["log_stage_record_id"],
            "parsed_command": parsed,
        }

    # Execute under the resolver's identity (full RBAC re-validation inside).
    exec_result = await _execute_admin_operation(user_data, parsed, original_instruction)

    record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=actor_role,
        commitment_type=commitment_type,
        subject_id=staged_id,
        summary=f"HITL {req.action}: {original_instruction[:200]}",
        subject_version=None,
        subject_hash=None,
        metadata=metadata,
    )
    PERSISTENCE.append_log_record(
        "admin", record,
        ledger_path=PERSISTENCE.get_log_ledger_path("admin"),
    )

    return {
        "staged_id": staged_id,
        "action": req.action,
        "parsed_command": parsed,
        "result": exec_result,
        "log_record_id": record["record_id"],
    }


# ─────────────────────────────────────────────────────────────
# HITL Staging Store — in-memory, single-process scope
# ─────────────────────────────────────────────────────────────

# Staged commands awaiting human resolution (keyed by staged_id).
_STAGED_COMMANDS: dict[str, dict[str, Any]] = {}
_STAGED_COMMANDS_LOCK = threading.Lock()
_STAGED_CMD_TTL_SECONDS: int = int(os.environ.get("LUMINA_STAGED_CMD_TTL_SECONDS", "300"))

_HITL_VALID_ACTIONS: frozenset[str] = frozenset({"accept", "reject", "modify"})


def _purge_expired_staged_commands() -> None:
    """Remove expired staged commands (called lazily on each stage/resolve call)."""
    now = time.time()
    with _STAGED_COMMANDS_LOCK:
        expired = [sid for sid, entry in _STAGED_COMMANDS.items() if entry["expires_at"] < now]
        for sid in expired:
            del _STAGED_COMMANDS[sid]


def _compute_schema_delta(original: dict[str, Any], modified: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow diff of two parsed-command dicts (operation/target/params)."""
    delta: dict[str, Any] = {}
    all_keys = set(original) | set(modified)
    for key in all_keys:
        orig_val = original.get(key)
        mod_val = modified.get(key)
        if orig_val != mod_val:
            delta[key] = {"from": orig_val, "to": mod_val}
    return delta


# ─────────────────────────────────────────────────────────────
# Logic Scraping — Admin Endpoints
# ─────────────────────────────────────────────────────────────

# In-memory store for running/completed scrapes (keyed by scrape_id).
_logic_scrape_results: dict[str, dict[str, Any]] = {}
_logic_scrape_lock = threading.Lock()


@app.post("/api/admin/logic-scrape")
async def start_logic_scrape(
    req: LogicScrapeRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Submit a logic scrape job.  Runs asynchronously; poll the scrape_id.

    Requires domain_authority role.
    """
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions — domain_authority required")

    # Resolve domain
    try:
        resolved = DOMAIN_REGISTRY.resolve_domain_id(req.domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics = PERSISTENCE.load_domain_physics(runtime["domain_physics_path"])

    logic_cfg = domain_physics.get("logic_scraping") or {}
    if not logic_cfg.get("enabled", False):
        raise HTTPException(
            status_code=400,
            detail=f"Logic scraping is not enabled for domain '{resolved}'",
        )

    from lumina.tools.logic_scraper import LogicScraper

    def _call_llm_via_slm(system_prompt: str, user_prompt: str) -> str:
        return call_slm(system_prompt, user_prompt)

    scraper = LogicScraper(
        call_llm_fn=_call_llm_via_slm,
        domain_physics=domain_physics,
        config=logic_cfg,
    )

    # Create a placeholder entry and launch in a background thread.
    import uuid as _uuid
    scrape_id = str(_uuid.uuid4())

    with _logic_scrape_lock:
        _logic_scrape_results[scrape_id] = {
            "scrape_id": scrape_id,
            "status": "running",
            "domain_id": resolved,
            "prompt": req.prompt,
        }

    def _run() -> None:
        try:
            result = scraper.scrape(
                prompt=req.prompt,
                iterations=req.iterations,
                domain_id=resolved,
                actor_id=user_data["sub"],
            )
            with _logic_scrape_lock:
                _logic_scrape_results[scrape_id] = {
                    "status": "completed",
                    **result.to_dict(),
                }
        except Exception as exc:
            log.exception("Logic scrape %s failed", scrape_id)
            with _logic_scrape_lock:
                _logic_scrape_results[scrape_id] = {
                    "scrape_id": scrape_id,
                    "status": "failed",
                    "error": str(exc),
                }

    thread = threading.Thread(target=_run, daemon=True, name=f"logic-scrape-{scrape_id}")
    thread.start()

    return {"scrape_id": scrape_id, "status": "running"}


@app.get("/api/admin/logic-scrape/{scrape_id}")
async def get_logic_scrape(
    scrape_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Poll a logic scrape result by scrape_id."""
    current = await get_current_user(credentials)
    require_auth(current)

    with _logic_scrape_lock:
        entry = _logic_scrape_results.get(scrape_id)

    if entry is None:
        raise HTTPException(status_code=404, detail="Scrape not found")
    return entry


# ─────────────────────────────────────────────────────────────
# Session Idle Timeout — Background Task
# ─────────────────────────────────────────────────────────────


async def _session_idle_cleanup() -> None:
    """Background task: close sessions that exceed the idle timeout."""
    while True:
        await asyncio.sleep(60)
        if SESSION_IDLE_TIMEOUT_MINUTES <= 0:
            continue
        timeout_seconds = SESSION_IDLE_TIMEOUT_MINUTES * 60
        now = time.time()
        expired_ids = [
            sid for sid, container in _session_containers.items()
            if (now - container.last_activity) > timeout_seconds
        ]
        for sid in expired_ids:
            log.info("Auto-closing idle session: %s", sid)
            try:
                _close_session(sid, "system", "system", "forced", "idle_timeout")
            except Exception:
                log.exception("Failed to auto-close session %s", sid)


@app.on_event("startup")
async def _start_idle_cleanup() -> None:
    _assert_system_physics_commitment()
    if SESSION_IDLE_TIMEOUT_MINUTES > 0:
        asyncio.create_task(_session_idle_cleanup())
        log.info("Session idle timeout enabled: %d minutes", SESSION_IDLE_TIMEOUT_MINUTES)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("LUMINA_PORT", "8000"))
    log.info("Starting Lumina API on port %s | LLM: %s", port, LLM_PROVIDER)
    if DOMAIN_REGISTRY.is_multi_domain:
        log.info("Multi-domain mode: %d domain(s)", len(DOMAIN_REGISTRY.list_domains()))
        for d in DOMAIN_REGISTRY.list_domains():
            log.info("  Domain: %s (%s)%s", d["domain_id"], d["label"], " [default]" if d["is_default"] else "")
    else:
        log.info("Single-domain mode: %s", RUNTIME_CONFIG_PATH)
    log.info("System Log directory: %s", LOG_DIR)
    log.info("Bootstrap mode: %s", BOOTSTRAP_MODE)
    log.info("CORS origins: %s", CORS_ORIGINS)
    uvicorn.run(app, host="0.0.0.0", port=port)
