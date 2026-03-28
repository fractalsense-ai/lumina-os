"""
slm.py — Small Language Model Compute Distribution Layer

Provides three capabilities:
1. **Librarian**: Glossary indexing, definition lookup, term fluency.
2. **Physics Interpreter**: Context compression during prompt packet
   assembly — matches incoming signals against domain physics to
   structure context before the LLM sees it.
3. **Command Translator**: Converts natural language admin instructions
   into structured system-level operations with RBAC enforcement.

Local-first default (Ollama/llama.cpp); cloud providers as opt-in.
"""

from __future__ import annotations

import enum
import json
import logging
import os
from pathlib import Path
from typing import Any

from lumina.core.persona_builder import PersonaContext, build_system_prompt

log = logging.getLogger("lumina-slm")

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

SLM_PROVIDER: str = os.environ.get("LUMINA_SLM_PROVIDER", "local")
SLM_MODEL: str = os.environ.get("LUMINA_SLM_MODEL", "gemma3:4b")
SLM_ENDPOINT: str = os.environ.get("LUMINA_SLM_ENDPOINT", "http://localhost:11434")
SLM_TIMEOUT: float = float(os.environ.get("LUMINA_SLM_TIMEOUT", "60"))
SLM_TEMPERATURE: float = 0.2
SLM_MAX_TOKENS: int = 512
# Physics interpretation needs larger output budget because the SLM must emit
# a complete JSON document enumerating matched invariants, standing orders, and
# a context summary.  Small models (e.g. gemma3:1b) truncate at 512 tokens,
# producing unterminated JSON strings.  This limit is applied only for that
# one call-site; all other SLM call-sites still use SLM_MAX_TOKENS.
SLM_PHYSICS_MAX_TOKENS: int = int(os.environ.get("LUMINA_SLM_PHYSICS_MAX_TOKENS", "2048"))
# Admin command translation also needs a higher token budget — the SLM must
# parse the instruction against the full operations list and emit a JSON dict.
SLM_COMMAND_MAX_TOKENS: int = int(os.environ.get("LUMINA_SLM_COMMAND_MAX_TOKENS", "1024"))


# ─────────────────────────────────────────────────────────────
# Task Weight Classification
# ─────────────────────────────────────────────────────────────


class TaskWeight(enum.Enum):
    """Classifies whether a prompt type is low-weight (SLM) or high-weight (LLM)."""

    LOW = "low"
    HIGH = "high"


_LOW_WEIGHT_TYPES: frozenset[str] = frozenset(
    {
        "definition_lookup",
        "physics_interpretation",
        "state_format",
        "admin_command",
        "field_validation",
        "document_extraction",
    }
)

_HIGH_WEIGHT_TYPES: frozenset[str] = frozenset(
    {
        "instruction",
        "correction",
        "scaffolded_hint",
        "more_steps_request",
        "novel_synthesis",
        "verification_request",
        "task_presentation",
        "hint",
    }
)


def classify_task_weight(
    prompt_type: str,
    overrides: dict[str, str] | None = None,
) -> TaskWeight:
    """Return LOW or HIGH weight for *prompt_type*.

    *overrides* lets domain packs reclassify custom prompt types.
    """
    if overrides:
        override_val = overrides.get(prompt_type, "").lower()
        if override_val == "low":
            return TaskWeight.LOW
        if override_val == "high":
            return TaskWeight.HIGH

    if prompt_type in _LOW_WEIGHT_TYPES:
        return TaskWeight.LOW
    # Default to HIGH for any unrecognised type — safer to send
    # unknown work to the LLM than risk a bad SLM response.
    return TaskWeight.HIGH


# ─────────────────────────────────────────────────────────────
# SLM Provider Implementations
# ─────────────────────────────────────────────────────────────


def _call_local_slm(system: str, user: str, model: str | None = None, max_tokens: int | None = None) -> str:
    """Call a local Ollama-compatible endpoint (OpenAI chat format)."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError(
            "httpx package is required for local SLM provider. "
            "Run: pip install httpx"
        )

    url = f"{SLM_ENDPOINT.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model or SLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": SLM_TEMPERATURE,
        "max_tokens": max_tokens if max_tokens is not None else SLM_MAX_TOKENS,
    }

    resp = httpx.post(url, json=payload, timeout=SLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"] or ""


def _call_openai_slm(system: str, user: str, model: str | None = None, max_tokens: int | None = None) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    client = OpenAI()
    response = client.chat.completions.create(
        model=model or SLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=SLM_TEMPERATURE,
        max_tokens=max_tokens if max_tokens is not None else SLM_MAX_TOKENS,
    )
    return response.choices[0].message.content or ""


def _call_anthropic_slm(system: str, user: str, model: str | None = None, max_tokens: int | None = None) -> str:
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    client = Anthropic()
    response = client.messages.create(
        model=model or SLM_MODEL,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=SLM_TEMPERATURE,
        max_tokens=max_tokens if max_tokens is not None else SLM_MAX_TOKENS,
    )
    return response.content[0].text


def _validate_slm_provider(provider: str) -> None:
    """Validate that the selected SLM provider can be reached."""
    if provider == "local":
        # Local provider health is checked at call time; no key needed.
        return
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required when LUMINA_SLM_PROVIDER=anthropic. "
                "For local SLM, set LUMINA_SLM_PROVIDER=local (default)."
            )
        return
    # Default: openai
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is required when LUMINA_SLM_PROVIDER=openai. "
            "For local SLM, set LUMINA_SLM_PROVIDER=local (default)."
        )


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


def slm_available() -> bool:
    """Return True if the configured SLM provider appears reachable.

    For cloud providers this checks for a valid API key.
    For the local provider it attempts a lightweight HTTP probe.
    """
    provider = SLM_PROVIDER
    if provider == "local":
        try:
            import httpx

            resp = httpx.get(f"{SLM_ENDPOINT.rstrip('/')}/", timeout=2.0)
            return resp.status_code < 500
        except Exception:
            return False
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return bool(os.environ.get("OPENAI_API_KEY"))


def call_slm(system: str, user: str, model: str | None = None, max_tokens: int | None = None) -> str:
    """Send a request to the configured SLM provider.

    Raises ``RuntimeError`` on configuration or transport errors.

    Parameters
    ----------
    max_tokens:
        Override the default ``SLM_MAX_TOKENS`` cap for this call.  Useful
        for calls that require a larger output budget (e.g. physics context
        interpretation which must emit a complete JSON document).
    """
    _validate_slm_provider(SLM_PROVIDER)
    if SLM_PROVIDER == "local":
        return _call_local_slm(system, user, model, max_tokens=max_tokens)
    if SLM_PROVIDER == "anthropic":
        return _call_anthropic_slm(system, user, model, max_tokens=max_tokens)
    return _call_openai_slm(system, user, model, max_tokens=max_tokens)


# ─────────────────────────────────────────────────────────────
# Role 1 — Librarian: Glossary Response Rendering
# ─────────────────────────────────────────────────────────────


def slm_render_glossary(glossary_entry: dict[str, Any]) -> str:
    """Use the SLM to render a fluent glossary definition response."""
    user_payload = json.dumps(glossary_entry, indent=2, ensure_ascii=False)
    return call_slm(system=build_system_prompt(PersonaContext.LIBRARIAN), user=user_payload)


# ─────────────────────────────────────────────────────────────
# Role 2 — Physics Interpreter: Context Compression
# ─────────────────────────────────────────────────────────────


def slm_interpret_physics_context(
    incoming_signals: dict[str, Any],
    domain_physics: dict[str, Any],
    glossary: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Use the SLM to compress incoming signals against domain physics.

    Returns a dict with ``matched_invariants``, ``applicable_standing_orders``,
    ``relevant_glossary_terms``, ``context_summary``, and
    ``suggested_evidence_fields``.  Falls back to an empty-enhancement dict on
    SLM failure.

    The full standing-order detail (action, trigger_condition, max_attempts,
    escalation_on_exhaust) and full invariant detail (description,
    standing_order_on_violation, handled_by) are included so the SLM can reason
    about which remediation paths are available for the current signals.
    """
    physics_subset = {
        "invariants": [
            {
                "id": inv.get("id"),
                "description": inv.get("description", ""),
                "severity": inv.get("severity"),
                "check": inv.get("check"),
                "standing_order_on_violation": inv.get("standing_order_on_violation"),
                "handled_by": inv.get("handled_by"),
            }
            for inv in (domain_physics.get("invariants") or [])
        ],
        "standing_orders": [
            {
                "id": so.get("id"),
                "action": so.get("action"),
                "description": so.get("description", ""),
                "trigger_condition": so.get("trigger_condition"),
                "max_attempts": so.get("max_attempts"),
                "escalation_on_exhaust": so.get("escalation_on_exhaust"),
            }
            for so in (domain_physics.get("standing_orders") or [])
        ],
        "escalation_triggers": [
            {
                "id": et.get("id"),
                "condition": et.get("condition", ""),
                "target_role": et.get("target_role"),
            }
            for et in (domain_physics.get("escalation_triggers") or [])
        ],
        "glossary_terms": [
            entry.get("term") for entry in (glossary or [])
        ],
    }

    user_payload = json.dumps(
        {"incoming_signals": incoming_signals, "domain_physics": physics_subset},
        indent=2,
        ensure_ascii=False,
    )

    try:
        raw = call_slm(
            system=build_system_prompt(PersonaContext.PHYSICS_INTERPRETER),
            user=user_payload,
            max_tokens=SLM_PHYSICS_MAX_TOKENS,
        )
        # Strip markdown fences if present.
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        result = json.loads(text.strip())
        if not isinstance(result, dict):
            return _empty_physics_context()
        return {
            "matched_invariants": result.get("matched_invariants") or [],
            "applicable_standing_orders": result.get("applicable_standing_orders") or [],
            "relevant_glossary_terms": result.get("relevant_glossary_terms") or [],
            "context_summary": str(result.get("context_summary", "")),
            "suggested_evidence_fields": result.get("suggested_evidence_fields") or {},
        }
    except Exception as exc:
        log.warning("SLM physics interpretation failed (%s); returning empty context", exc)
        return _empty_physics_context()


def _empty_physics_context() -> dict[str, Any]:
    return {
        "matched_invariants": [],
        "applicable_standing_orders": [],
        "relevant_glossary_terms": [],
        "context_summary": "",
        "suggested_evidence_fields": {},
    }


# ─────────────────────────────────────────────────────────────
# Role 3 — Command Translator: Admin Command Parsing
# ─────────────────────────────────────────────────────────────


# ── Admin Operations Loader ───────────────────────────────────
#
# Canonical source: domain-packs/system/cfg/admin-operations.yaml
# The loader reads the YAML at first access and caches the result.
# If the file is missing or malformed, a warning is logged and the
# engine falls back to _FALLBACK_ADMIN_OPERATIONS — a minimal
# inline copy kept only for graceful degradation.

_admin_ops_cache: list[dict[str, Any]] | None = None


def _resolve_admin_ops_path() -> Path | None:
    """Locate the admin-operations YAML via env → system domain physics → well-known default."""
    env_path = os.environ.get("LUMINA_ADMIN_OPS_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p

    # Try well-known default relative to repo root.
    repo_root = Path(os.environ.get("LUMINA_REPO_ROOT", Path(__file__).resolve().parents[3]))
    default = repo_root / "domain-packs" / "system" / "cfg" / "admin-operations.yaml"
    if default.is_file():
        return default

    return None


def _load_admin_operations_from_yaml(yaml_path: Path) -> list[dict[str, Any]]:
    """Parse admin-operations.yaml into the list shape expected by the SLM."""
    from lumina.core.yaml_loader import load_yaml

    raw = load_yaml(str(yaml_path))
    if not isinstance(raw, dict) or "operations" not in raw:
        raise ValueError(f"admin-operations.yaml must contain an 'operations' key: {yaml_path}")
    ops = raw["operations"]
    if not isinstance(ops, list):
        raise ValueError(f"'operations' must be a list: {yaml_path}")
    result: list[dict[str, Any]] = []
    for entry in ops:
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        result.append({
            "name": entry["name"],
            "description": entry.get("description", ""),
            "params_schema": entry.get("params") or {},
        })
    return result


def _get_admin_operations() -> list[dict[str, Any]]:
    """Return admin operations, loading from YAML on first call with fallback."""
    global _admin_ops_cache
    if _admin_ops_cache is not None:
        return _admin_ops_cache

    yaml_path = _resolve_admin_ops_path()
    if yaml_path is not None:
        try:
            _admin_ops_cache = _load_admin_operations_from_yaml(yaml_path)
            log.info("Loaded %d admin operations from %s", len(_admin_ops_cache), yaml_path)
            return _admin_ops_cache
        except Exception as exc:
            log.warning("Failed to load admin-operations.yaml (%s); using fallback", exc)

    _admin_ops_cache = _FALLBACK_ADMIN_OPERATIONS
    return _admin_ops_cache


# Minimal fallback — kept only for graceful degradation when the YAML is absent.
_FALLBACK_ADMIN_OPERATIONS: list[dict[str, Any]] = [
    {"name": "update_domain_physics", "description": "Update fields in a domain's physics configuration.", "params_schema": {"domain_id": "string", "updates": "object"}},
    {"name": "commit_domain_physics", "description": "Commit the current domain physics hash to the System Logs.", "params_schema": {"domain_id": "string"}},
    {"name": "update_user_role", "description": "Change a user's role.", "params_schema": {"user_id": "string", "new_role": "string", "governed_modules": "array of strings"}},
    {"name": "deactivate_user", "description": "Deactivate a user account.", "params_schema": {"user_id": "string"}},
    {"name": "assign_domain_role", "description": "Grant a user access to a domain module.", "params_schema": {"user_id": "string", "module_id": "string", "domain_role": "string"}},
    {"name": "revoke_domain_role", "description": "Revoke a user's access to a domain module.", "params_schema": {"user_id": "string", "module_id": "string"}},
    {"name": "resolve_escalation", "description": "Approve, reject, or defer an escalation.", "params_schema": {"escalation_id": "string", "resolution": "string", "rationale": "string"}},
    {"name": "ingest_document", "description": "Upload and ingest a document.", "params_schema": {"domain_id": "string", "module_id": "string", "filename": "string"}},
    {"name": "list_ingestions", "description": "List pending ingestion drafts.", "params_schema": {"domain_id": "string", "status": "string"}},
    {"name": "review_ingestion", "description": "Show SLM-generated interpretations for an ingestion.", "params_schema": {"ingestion_id": "string"}},
    {"name": "approve_interpretation", "description": "Approve an interpretation variant.", "params_schema": {"ingestion_id": "string", "interpretation_label": "string"}},
    {"name": "reject_ingestion", "description": "Reject an ingestion with a reason.", "params_schema": {"ingestion_id": "string", "reason": "string"}},
    {"name": "list_escalations", "description": "List open escalation events.", "params_schema": {"domain_id": "string", "status": "string"}},
    {"name": "explain_reasoning", "description": "Explain a system decision.", "params_schema": {"event_id": "string"}},
    {"name": "module_status", "description": "Show the current status of a domain module.", "params_schema": {"module_id": "string", "domain_id": "string"}},
    {"name": "trigger_night_cycle", "description": "Manually trigger night cycle.", "params_schema": {"domain_id": "string", "tasks": "array of strings"}},
    {"name": "night_cycle_status", "description": "Check night cycle scheduler status.", "params_schema": {}},
    {"name": "review_proposals", "description": "Show pending night cycle proposals.", "params_schema": {"domain_id": "string"}},
    {"name": "invite_user", "description": "Create and invite a new user.", "params_schema": {"username": "string", "role": "string", "email": "string", "governed_modules": "array of strings"}},
    {"name": "list_commands", "description": "List available admin commands.", "params_schema": {"include_details": "boolean"}},
    {"name": "list_domains", "description": "List all registered domains.", "params_schema": {}},
    {"name": "list_modules", "description": "List modules within a domain.", "params_schema": {"domain_id": "string"}},
]

# Public alias — existing code references ADMIN_OPERATIONS (read-only).
ADMIN_OPERATIONS = _FALLBACK_ADMIN_OPERATIONS


def _compact_operations(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip verbose ``params_schema`` descriptions to reduce token count.

    Small models struggle with the full ~2 KB operations payload.  This keeps
    only the parameter names (as a list) so the SLM can still map intent →
    operation without burning tokens on schema prose.
    """
    compacted: list[dict[str, Any]] = []
    for op in ops:
        entry: dict[str, Any] = {
            "name": op["name"],
            "description": op["description"],
        }
        schema = op.get("params_schema")
        if isinstance(schema, dict):
            entry["params"] = list(schema.keys())
        compacted.append(entry)
    return compacted


def slm_parse_admin_command(
    natural_language: str,
    available_operations: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Use the SLM to translate a natural language instruction into a structured command.

    Returns a dict ``{"operation", "target", "params"}`` or ``None`` if unparseable.
    """
    ops = available_operations or _get_admin_operations()
    ops = _compact_operations(ops)
    user_payload = json.dumps(
        {"instruction": natural_language, "available_operations": ops},
        indent=2,
        ensure_ascii=False,
    )

    try:
        raw = call_slm(
            system=build_system_prompt(PersonaContext.COMMAND_TRANSLATOR),
            user=user_payload,
            max_tokens=SLM_COMMAND_MAX_TOKENS,
        )
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
        if text.lower() in ("null", "none", ""):
            return None
        # Handle prose-wrapped output: extract the first {...} JSON object if
        # the model prefixed the JSON with explanatory text.
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                text = text[start : end + 1]
        log.debug("slm_parse_admin_command extracted text: %r", text[:200])
        result = json.loads(text)
        if not isinstance(result, dict):
            return None
        if "operation" not in result:
            return None
        return {
            "operation": str(result["operation"]),
            "target": str(result.get("target", "")),
            "params": result.get("params") or {},
        }
    except Exception:
        log.warning("SLM admin command parsing failed for input: %r", natural_language[:80])
        return None
