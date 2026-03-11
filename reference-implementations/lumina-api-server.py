"""
lumina-api-server.py — Project Lumina Integration Server

Generic runtime host for D.S.A. orchestration:
- Loads runtime behavior from domain-owned config
- Keeps core server free of domain-specific prompt/state logic
- Routes each turn through orchestrator prompt contracts and CTL
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

# Ensure local reference-implementation imports resolve regardless of launch style.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from auth import (
    AuthError,
    TokenExpiredError,
    TokenInvalidError,
    VALID_ROLES,
    create_jwt,
    hash_password,
    verify_jwt,
    verify_password,
)
from domain_registry import DomainNotFoundError, DomainRegistry
from filesystem_persistence import FilesystemPersistenceAdapter
from permissions import Operation, check_permission
from persistence_adapter import PersistenceAdapter
from runtime_loader import load_runtime_context

# ─────────────────────────────────────────────────────────────
# Resolve paths and imports
# ─────────────────────────────────────────────────────────────

_REPO_ROOT = _THIS_DIR.parent

_orch_spec = importlib.util.spec_from_file_location(
    "dsa_orchestrator",
    str(_THIS_DIR / "dsa-orchestrator.py"),
)
_orch_mod = importlib.util.module_from_spec(_orch_spec)  # type: ignore[arg-type]
sys.modules["dsa_orchestrator"] = _orch_mod
_orch_spec.loader.exec_module(_orch_mod)  # type: ignore[union-attr]

DSAOrchestrator = _orch_mod.DSAOrchestrator

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

LLM_PROVIDER = os.environ.get("LUMINA_LLM_PROVIDER", "openai")
OPENAI_MODEL = os.environ.get("LUMINA_OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL = os.environ.get("LUMINA_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
RUNTIME_CONFIG_PATH = os.environ.get("LUMINA_RUNTIME_CONFIG_PATH")
DOMAIN_REGISTRY_PATH = os.environ.get("LUMINA_DOMAIN_REGISTRY_PATH")
PERSISTENCE_BACKEND = os.environ.get("LUMINA_PERSISTENCE_BACKEND", "filesystem").strip().lower()
DB_URL = os.environ.get("LUMINA_DB_URL")
ENFORCE_POLICY_COMMITMENT = os.environ.get("LUMINA_ENFORCE_POLICY_COMMITMENT", "true").strip().lower() not in {"0", "false", "no"}
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("LUMINA_CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
BOOTSTRAP_MODE: bool = os.environ.get("LUMINA_BOOTSTRAP_MODE", "true").strip().lower() not in {"0", "false", "no"}

# ─────────────────────────────────────────────────────────────
# Domain Registry (replaces single-domain RUNTIME singleton)
# ─────────────────────────────────────────────────────────────

DOMAIN_REGISTRY = DomainRegistry(
    repo_root=_REPO_ROOT,
    registry_path=DOMAIN_REGISTRY_PATH,
    single_config_path=RUNTIME_CONFIG_PATH,
    load_runtime_context_fn=load_runtime_context,
)

_DEFAULT_CTL_DIR = Path(tempfile.gettempdir()) / "lumina-ctl"
CTL_DIR = Path(os.environ.get("LUMINA_CTL_DIR", str(_DEFAULT_CTL_DIR)))
CTL_DIR.mkdir(parents=True, exist_ok=True)


def _build_persistence_adapter() -> PersistenceAdapter:
    if PERSISTENCE_BACKEND == "sqlite":
        from sqlite_persistence import SQLitePersistenceAdapter

        return SQLitePersistenceAdapter(repo_root=_REPO_ROOT, database_url=DB_URL)
    return FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, ctl_dir=CTL_DIR)


PERSISTENCE: PersistenceAdapter = _build_persistence_adapter()


def _get_generate_problem_fn(runtime: dict[str, Any]) -> Any:
    """Resolve the ``generate_problem`` callable from the domain-pack's
    reference-implementations directory, mirroring how runtime_loader
    loads domain adapters via importlib.
    """
    domain_step_cfg = (runtime.get("adapters") or {}).get("domain_step") or {}
    module_path = domain_step_cfg.get("module_path", "")
    if module_path:
        gen_path = Path(_REPO_ROOT) / Path(module_path).parent / "problem_generator.py"
        if gen_path.is_file():
            spec = importlib.util.spec_from_file_location("_problem_generator", str(gen_path))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return getattr(mod, "generate_problem", None)
    return None


def _default_current_problem(task_spec: dict[str, Any], runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a session-scoped problem via the deterministic generator.

    Falls back to the task_spec's ``current_problem`` if the generator
    or tier config is unavailable.
    """
    # Try dynamic generation from domain-physics tiers
    if runtime is not None:
        domain = runtime.get("domain") or {}
        subsystem_configs = domain.get("subsystem_configs") or {}
        tiers = subsystem_configs.get("equation_difficulty_tiers")
        if isinstance(tiers, list) and tiers:
            try:
                gen_fn = _get_generate_problem_fn(runtime)
                if gen_fn is not None:
                    difficulty = float(task_spec.get("nominal_difficulty", 0.5))
                    return gen_fn(difficulty, tiers)
            except Exception:
                log.warning("Problem generator unavailable; falling back to task_spec")

    # Fallback: use whatever is in the task_spec
    current_problem = task_spec.get("current_problem")
    if isinstance(current_problem, dict):
        return dict(current_problem)

    equation = task_spec.get("equation") or "2x + 3 = 11"
    target_variable = task_spec.get("target_variable") or "x"
    expected_answer = task_spec.get("expected_answer") or "x = 4"
    return {
        "equation": str(equation),
        "target_variable": str(target_variable),
        "expected_answer": str(expected_answer),
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


def _strip_latex_delimiters(text: str) -> str:
    """Remove LaTeX inline \\( \\) and display \\[ \\] delimiters, keeping inner content."""
    text = _LATEX_INLINE_RE.sub(r"\1", text)
    text = _LATEX_DISPLAY_RE.sub(r"\1", text)
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
            "Policy commitment mismatch: active module domain-physics hash is not CTL-committed. "
            "Commit the module domain-physics.json hash before activation."
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


def interpret_turn_input(input_text: str, task_context: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    interpreter = runtime["turn_interpreter_fn"]
    kwargs: dict[str, Any] = {
        "call_llm": call_llm,
        "input_text": input_text,
        "task_context": task_context,
        "prompt_text": runtime["turn_interpretation_prompt"],
        "default_fields": runtime["turn_input_defaults"],
        "tool_fns": runtime.get("tool_fns"),
    }
    nlp_fn = runtime.get("nlp_pre_interpreter_fn")
    if nlp_fn is not None:
        kwargs["nlp_pre_interpreter_fn"] = nlp_fn
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
    )

    def __init__(
        self,
        orchestrator: Any,
        task_spec: dict[str, Any],
        current_problem: dict[str, Any],
        turn_count: int,
        domain_id: str,
        problem_presented_at: float,
    ) -> None:
        self.orchestrator = orchestrator
        self.task_spec = task_spec
        self.current_problem = current_problem
        self.turn_count = turn_count
        self.domain_id = domain_id
        self.problem_presented_at = problem_presented_at

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

    __slots__ = ("active_domain_id", "contexts", "user")

    def __init__(self, active_domain_id: str, user: dict[str, Any] | None = None) -> None:
        self.active_domain_id = active_domain_id
        self.contexts: dict[str, DomainContext] = {}
        self.user = user

    @property
    def active_context(self) -> DomainContext:
        return self.contexts[self.active_domain_id]


_session_containers: dict[str, SessionContainer] = {}


def _build_domain_context(
    session_id: str,
    resolved_domain_id: str,
    persisted_state: dict[str, Any] | None = None,
) -> DomainContext:
    """Construct a fresh DomainContext for a domain (shared by create + switch)."""
    runtime = DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)

    _assert_policy_commitment(runtime)
    domain_physics_path = Path(runtime["domain_physics_path"])
    subject_profile_path = Path(runtime["subject_profile_path"])
    domain = PERSISTENCE.load_domain_physics(str(domain_physics_path))
    profile = PERSISTENCE.load_subject_profile(str(subject_profile_path))
    ledger_path = PERSISTENCE.get_ctl_ledger_path(session_id, domain_id=resolved_domain_id)
    ps = persisted_state or {}

    state_builder = runtime["state_builder_fn"]
    domain_step = runtime["domain_step_fn"]
    domain_params = dict(runtime["domain_step_params"])

    initial_state = state_builder(profile)

    orch = DSAOrchestrator(
        domain_physics=domain,
        subject_profile=profile,
        ledger_path=str(ledger_path),
        session_id=session_id,
        domain_lib_step_fn=lambda state, task, ev: domain_step(state, task, ev, domain_params),
        initial_state=initial_state,
        action_prompt_type_map=runtime.get("action_prompt_type_map") or {},
        policy_commitment=_policy_commitment_payload(runtime),
        ctl_append_callback=lambda sid, record: PERSISTENCE.append_ctl_record(
            sid,
            record,
            ledger_path=str(ledger_path),
        ),
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
    )


def get_or_create_session(session_id: str, domain_id: str | None = None) -> dict[str, Any]:
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
                ctx = _build_domain_context(session_id, resolved_domain_id_checked)
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
            PERSISTENCE.append_ctl_record(
                session_id,
                {
                    "event": "domain_switch",
                    "from_domain": previous_domain,
                    "to_domain": container.active_domain_id,
                    "timestamp": time.time(),
                    "session_id": session_id,
                },
                ledger_path=PERSISTENCE.get_ctl_ledger_path(session_id, domain_id="_meta"),
            )

        return container.active_context.to_session_dict()

    # ── New session ──────────────────────────────────────────
    resolved_domain_id = DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    ctx = _build_domain_context(session_id, resolved_domain_id)

    container = SessionContainer(active_domain_id=resolved_domain_id)
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
) -> dict[str, Any]:
    session = get_or_create_session(session_id, domain_id=domain_id)
    orch: DSAOrchestrator = session["orchestrator"]
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
        else:
            llm_response = call_llm(
                system=system_prompt,
                user=json.dumps(llm_payload, indent=2, ensure_ascii=False),
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
    else:
        turn_data = interpret_turn_input(input_text, task_context, runtime)
    turn_data = _normalize_turn_data(turn_data, runtime.get("turn_input_schema") or {})

    # Inject server-side solve elapsed time (more reliable than LLM estimate)
    presented_at = session.get("problem_presented_at")
    if presented_at is not None:
        turn_data["solve_elapsed_sec"] = time.time() - presented_at

    log.info("[%s] Turn Data: %s", session_id, json.dumps(turn_data, default=str))

    turn_provenance: dict[str, Any] = dict(runtime_provenance)
    turn_provenance["turn_data_hash"] = _canonical_sha256(turn_data)

    prompt_contract, resolved_action = orch.process_turn(
        task_spec,
        turn_data,
        provenance_metadata=turn_provenance,
    )

    reported_status = turn_data.get("problem_status")
    if isinstance(reported_status, str) and reported_status.strip():
        current_problem["status"] = reported_status.strip()

    # ── Fluency-gated problem advancement ─────────────────────
    fluency_decision = {}
    domain_lib_decision = getattr(orch, "last_domain_lib_decision", None) or {}
    if isinstance(domain_lib_decision.get("fluency"), dict):
        fluency_decision = domain_lib_decision["fluency"]

    should_advance = fluency_decision.get("advanced", False)
    correctness = turn_data.get("correctness", "partial")

    if should_advance or (
        resolved_action == "task_presentation"
        and correctness == "correct"
        and turn_data.get("substitution_check") is True
    ):
        domain = (runtime.get("domain") or {}).get("subsystem_configs") or {}
        tiers = domain.get("equation_difficulty_tiers")
        if isinstance(tiers, list) and tiers:
            try:
                gen_fn = _get_generate_problem_fn(runtime)
                if gen_fn is not None:
                    if should_advance:
                        next_tier = fluency_decision.get("next_tier", "")
                        tier_objs = {str(t.get("tier_id")): t for t in tiers}
                        target_tier = tier_objs.get(next_tier, tiers[-1])
                        diff = (float(target_tier.get("min_difficulty", 0)) +
                                float(target_tier.get("max_difficulty", 1))) / 2
                    else:
                        diff = float(task_spec.get("nominal_difficulty", 0.5))
                    current_problem = gen_fn(diff, tiers)
            except Exception:
                log.warning("Problem generation on advance failed")
        session["problem_presented_at"] = time.time()

    session["current_problem"] = current_problem
    session["turn_count"] += 1

    # Sync mutations back to the DomainContext in the session container
    container = _session_containers.get(session_id)
    if container is not None:
        container.active_context.sync_from_dict(session)
        _persist_session_container(session_id, container)
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
        for r in orch.ctl_records[-2:]
    )

    tool_results = apply_tool_call_policy(
        resolved_action=resolved_action,
        prompt_contract=prompt_contract,
        turn_data=turn_data,
        task_spec=task_spec,
        runtime=runtime,
    )

    if deterministic_response:
        llm_payload = dict(prompt_contract)
        llm_payload["current_problem"] = current_problem
        llm_payload["student_message"] = input_text
        if tool_results:
            llm_payload["tool_results"] = tool_results
        llm_response = render_contract_response(prompt_contract, runtime)
    else:
        llm_payload = dict(prompt_contract)
        llm_payload["current_problem"] = current_problem
        llm_payload["student_message"] = input_text
        if tool_results:
            llm_payload["tool_results"] = tool_results
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
    version="0.3.0",
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


class ChatResponse(BaseModel):
    session_id: str
    response: str
    action: str
    prompt_type: str
    escalated: bool
    tool_results: list[dict[str, Any]] | None = None
    domain_id: str | None = None


class ToolRequest(BaseModel):
    payload: dict[str, Any]


class ToolResponse(BaseModel):
    tool_id: str
    result: dict[str, Any]


class CtlValidateResponse(BaseModel):
    result: dict[str, Any]


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
            # Fall back to default domain
            try:
                resolved_domain_id = DOMAIN_REGISTRY.resolve_domain_id(None)
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Could not determine domain. Please specify domain_id.",
                )
            routing_record["method"] = "default"
            routing_record["confidence"] = 0.0

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
        PERSISTENCE.append_ctl_record(
            session_id,
            routing_record,
            ledger_path=PERSISTENCE.get_ctl_ledger_path(session_id, domain_id="_meta"),
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


@app.get("/api/ctl/validate", response_model=CtlValidateResponse)
async def validate_ctl(
    session_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CtlValidateResponse:
    """Validate CTL hash-chain integrity for one session or all known sessions."""
    user = await get_current_user(credentials)
    if user is not None:
        require_role(user, "root", "domain_authority", "qa", "auditor")
    try:
        result = await run_in_threadpool(PERSISTENCE.validate_ctl_chain, session_id)
    except Exception as exc:
        log.exception("CTL validation failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return CtlValidateResponse(result=result)


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
    log.info("CTL directory: %s", CTL_DIR)
    log.info("Bootstrap mode: %s", BOOTSTRAP_MODE)
    log.info("CORS origins: %s", CORS_ORIGINS)
    uvicorn.run(app, host="0.0.0.0", port=port)
