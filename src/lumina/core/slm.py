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
from typing import Any

log = logging.getLogger("lumina-slm")

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

SLM_PROVIDER: str = os.environ.get("LUMINA_SLM_PROVIDER", "local")
SLM_MODEL: str = os.environ.get("LUMINA_SLM_MODEL", "phi3")
SLM_ENDPOINT: str = os.environ.get("LUMINA_SLM_ENDPOINT", "http://localhost:11434")
SLM_TEMPERATURE: float = 0.2
SLM_MAX_TOKENS: int = 512


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


def _call_local_slm(system: str, user: str, model: str | None = None) -> str:
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
        "max_tokens": SLM_MAX_TOKENS,
    }

    resp = httpx.post(url, json=payload, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"] or ""


def _call_openai_slm(system: str, user: str, model: str | None = None) -> str:
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
        max_tokens=SLM_MAX_TOKENS,
    )
    return response.choices[0].message.content or ""


def _call_anthropic_slm(system: str, user: str, model: str | None = None) -> str:
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
        max_tokens=SLM_MAX_TOKENS,
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


def call_slm(system: str, user: str, model: str | None = None) -> str:
    """Send a request to the configured SLM provider.

    Raises ``RuntimeError`` on configuration or transport errors.
    """
    _validate_slm_provider(SLM_PROVIDER)
    if SLM_PROVIDER == "local":
        return _call_local_slm(system, user, model)
    if SLM_PROVIDER == "anthropic":
        return _call_anthropic_slm(system, user, model)
    return _call_openai_slm(system, user, model)


# ─────────────────────────────────────────────────────────────
# Role 1 — Librarian: Glossary Response Rendering
# ─────────────────────────────────────────────────────────────

_LIBRARIAN_SYSTEM_PROMPT = (
    "You are a domain librarian. "
    "Provide clear, concise definitions using ONLY the provided glossary entry. "
    "Include the example and mention related terms naturally. "
    "Do not fabricate information beyond what is provided. "
    "Keep the response to 2-3 sentences."
)


def slm_render_glossary(glossary_entry: dict[str, Any]) -> str:
    """Use the SLM to render a fluent glossary definition response."""
    user_payload = json.dumps(glossary_entry, indent=2, ensure_ascii=False)
    return call_slm(system=_LIBRARIAN_SYSTEM_PROMPT, user=user_payload)


# ─────────────────────────────────────────────────────────────
# Role 2 — Physics Interpreter: Context Compression
# ─────────────────────────────────────────────────────────────

_PHYSICS_INTERPRETER_PROMPT = (
    "You are a domain physics interpreter for a structured orchestration system. "
    "Given incoming signals (NLP anchors, sensor data, tool outputs) and domain physics rules "
    "(invariants, standing orders, glossary), identify which invariants and glossary terms "
    "are relevant to the current input. Compress the context into a concise summary.\n\n"
    "Respond in JSON only with this structure:\n"
    "{\n"
    '  "matched_invariants": ["invariant_id_1", ...],\n'
    '  "relevant_glossary_terms": ["term1", ...],\n'
    '  "context_summary": "One-sentence summary of what the input means in domain context",\n'
    '  "suggested_evidence_fields": {"field_name": value, ...}\n'
    "}"
)


def slm_interpret_physics_context(
    incoming_signals: dict[str, Any],
    domain_physics: dict[str, Any],
    glossary: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Use the SLM to compress incoming signals against domain physics.

    Returns a dict with ``matched_invariants``, ``relevant_glossary_terms``,
    ``context_summary``, and ``suggested_evidence_fields``.  Falls back to
    an empty-enhancement dict on SLM failure.
    """
    physics_subset = {
        "invariants": [
            {"id": inv.get("id"), "check": inv.get("check"), "severity": inv.get("severity")}
            for inv in (domain_physics.get("invariants") or [])
        ],
        "standing_orders": [
            {"id": so.get("id")}
            for so in (domain_physics.get("standing_orders") or [])
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
        raw = call_slm(system=_PHYSICS_INTERPRETER_PROMPT, user=user_payload)
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
        "relevant_glossary_terms": [],
        "context_summary": "",
        "suggested_evidence_fields": {},
    }


# ─────────────────────────────────────────────────────────────
# Role 3 — Command Translator: Admin Command Parsing
# ─────────────────────────────────────────────────────────────

_COMMAND_TRANSLATOR_PROMPT = (
    "You are a system command interpreter for a structured orchestration platform. "
    "Parse the user instruction into a structured operation using ONLY the operations "
    "from the provided list. If the instruction does not match any available operation, "
    "return null.\n\n"
    "Respond in JSON only with this structure (or null):\n"
    "{\n"
    '  "operation": "operation_name",\n'
    '  "target": "target_resource_identifier",\n'
    '  "params": { ... }\n'
    "}"
)

# Operations available for SLM command translation.
ADMIN_OPERATIONS: list[dict[str, Any]] = [
    {
        "name": "update_domain_physics",
        "description": "Update fields in a domain's physics configuration.",
        "params_schema": {
            "domain_id": "string — target domain identifier",
            "updates": "object — key/value pairs to merge into domain physics",
        },
    },
    {
        "name": "commit_domain_physics",
        "description": "Commit the current domain physics hash to the CTL.",
        "params_schema": {
            "domain_id": "string — target domain identifier",
        },
    },
    {
        "name": "update_user_role",
        "description": "Change a user's role.",
        "params_schema": {
            "user_id": "string — target user identifier",
            "new_role": "string — one of: root, domain_authority, it_support, qa, auditor, user",
        },
    },
    {
        "name": "deactivate_user",
        "description": "Deactivate a user account.",
        "params_schema": {
            "user_id": "string — target user identifier",
        },
    },
    {
        "name": "resolve_escalation",
        "description": "Approve, reject, or defer an escalation.",
        "params_schema": {
            "escalation_id": "string",
            "resolution": "string — one of: approved, rejected, deferred",
            "rationale": "string — reason for resolution",
        },
    },
]


def slm_parse_admin_command(
    natural_language: str,
    available_operations: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Use the SLM to translate a natural language instruction into a structured command.

    Returns a dict ``{"operation", "target", "params"}`` or ``None`` if unparseable.
    """
    ops = available_operations or ADMIN_OPERATIONS
    user_payload = json.dumps(
        {"instruction": natural_language, "available_operations": ops},
        indent=2,
        ensure_ascii=False,
    )

    try:
        raw = call_slm(system=_COMMAND_TRANSLATOR_PROMPT, user=user_payload)
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
        if text.lower() in ("null", "none", ""):
            return None
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
        log.debug("SLM admin command parsing failed")
        return None
