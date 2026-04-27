"""Deterministic NLP pre-interpreter for system domain.

Runs lightweight pattern-based extractors on operator messages BEFORE
the LLM turn interpreter, producing structured anchors that are injected
into the LLM prompt as grounding context.
"""

from __future__ import annotations

import re
from typing import Any

# ── Admin verb extractor ─────────────────────────────────────────────────────

_MUTATION_VERBS = re.compile(
    r"\b(remove|revoke|delete|add|give|assign|grant|promote|change|deactivate"
    r"|update|invite|set|modify|rotate|reset|suspend)\b",
    re.IGNORECASE,
)

_READ_VERBS = re.compile(
    r"\b(show|list|get|check|view|what|status|tell|describe|display|find|inspect)\b",
    re.IGNORECASE,
)


def extract_admin_verb(input_text: str) -> dict[str, Any]:
    """Detect the primary verb intent (mutation vs read).

    Returns
    -------
    dict
        ``intent_type`` ("mutation" | "read" | "unknown"), ``verb``, ``confidence``.
    """
    mutation_match = _MUTATION_VERBS.search(input_text)
    read_match = _READ_VERBS.search(input_text)

    if mutation_match and not read_match:
        return {
            "intent_type": "mutation",
            "verb": mutation_match.group(1).lower(),
            "confidence": 0.90,
        }

    if mutation_match and read_match:
        # Both found — earliest match wins; mutation near start → likely operative
        if mutation_match.start() <= read_match.start():
            return {
                "intent_type": "mutation",
                "verb": mutation_match.group(1).lower(),
                "confidence": 0.80,
            }
        return {
            "intent_type": "read",
            "verb": read_match.group(1).lower(),
            "confidence": 0.80,
        }

    if read_match:
        return {
            "intent_type": "read",
            "verb": read_match.group(1).lower(),
            "confidence": 0.90,
        }

    return {"intent_type": "unknown", "verb": "", "confidence": 0.0}


# ── Target user extractor ────────────────────────────────────────────────────

_USER_NAMED = re.compile(r"user\s+named\s+(\w+)", re.IGNORECASE)
_FOR_FROM_USER = re.compile(r"(?:for|from|to)\s+user\s+(\w+)", re.IGNORECASE)
_USER_BARE = re.compile(r"\buser\s+(\w+)\b", re.IGNORECASE)


def extract_target_user(input_text: str) -> dict[str, Any]:
    """Extract the target username from the input text.

    Returns
    -------
    dict
        ``target_user`` (str | None), ``confidence``.
    """
    m = _USER_NAMED.search(input_text)
    if m:
        return {"target_user": m.group(1), "confidence": 0.95}

    m = _FOR_FROM_USER.search(input_text)
    if m:
        return {"target_user": m.group(1), "confidence": 0.95}

    m = _USER_BARE.search(input_text)
    if m:
        return {"target_user": m.group(1), "confidence": 0.85}

    return {"target_user": None, "confidence": 0.0}


# ── Target role extractor ────────────────────────────────────────────────────

# Ordered longest-first so "domain authority" matches before bare "user".
_ROLE_PHRASES: list[tuple[str, str]] = [
    ("domain_authority", "admin"),
    ("domain authority", "admin"),
    ("it_support", "super_admin"),
    ("it support", "super_admin"),
    ("auditor", "half_operator"),
    ("root", "root"),
    ("qa", "operator"),
    ("user", "user"),
]

_DOMAIN_SCOPED_DA = re.compile(
    r"\b(?:domain\s+authority|da)\s+(?:access\s+to\s+|for\s+)?(\w+)",
    re.IGNORECASE,
)

_X_ONLY = re.compile(r"\b(\w+)\s+only\b", re.IGNORECASE)

_REMOVE_REVOKE_ROOT = re.compile(r"\b(?:remove|revoke)\s+root\b", re.IGNORECASE)


def extract_target_role(input_text: str) -> dict[str, Any]:
    """Detect the target role and any domain scope from the input.

    Returns
    -------
    dict
        ``target_role`` (str | None), ``governed_domains`` (list | None),
        ``confidence``.
    """
    result: dict[str, Any] = {
        "target_role": None,
        "governed_domains": None,
        "confidence": 0.0,
    }

    # Most specific: "domain authority access to <domain>" / "da <domain>"
    m = _DOMAIN_SCOPED_DA.search(input_text)
    if m:
        result["target_role"] = "admin"
        result["governed_domains"] = [m.group(1).lower()]
        result["confidence"] = 0.85
        return result

    # Plain role name
    lower = input_text.lower()
    for phrase, role in _ROLE_PHRASES:
        if phrase in lower:
            result["target_role"] = role
            result["confidence"] = 0.85
            break

    # If DA was matched and there's an "X only" pattern, capture domain scope
    if result["target_role"] == "admin":
        m_only = _X_ONLY.search(input_text)
        if m_only:
            result["governed_domains"] = [m_only.group(1).lower()]

    # "remove root" / "revoke root" → definite root role target
    if _REMOVE_REVOKE_ROOT.search(input_text):
        result["target_role"] = "root"
        result["confidence"] = 0.90

    return result


# ── Compound command detector ────────────────────────────────────────────────

_VERB_COMPOUND_VERB = re.compile(
    r"(?:remove|revoke|delete|add|give|assign|grant|promote|change"
    r"|deactivate|update|invite|set|modify|rotate|reset|suspend)"
    r"[^.!?]{0,80}"
    r"(?:and|also|as\s+well\s+as|plus|\bthen\b)"
    r"[^.!?]{0,80}"
    r"(?:remove|revoke|delete|add|give|assign|grant|promote|change"
    r"|deactivate|update|invite|set|modify|rotate|reset|suspend)",
    re.IGNORECASE,
)


def detect_compound_command(input_text: str) -> dict[str, Any]:
    """Detect AND-joined compound operations in the input.

    Returns
    -------
    dict
        ``is_compound`` (bool), ``operation_count_estimate`` (int).
    """
    if _VERB_COMPOUND_VERB.search(input_text):
        return {"is_compound": True, "operation_count_estimate": 2}
    return {"is_compound": False, "operation_count_estimate": 1}


# ── Glossary term matcher ────────────────────────────────────────────────────

_SYSTEM_GLOSSARY: frozenset[str] = frozenset([
    "ctl", "commitment_record", "trace_event", "system_physics", "domain_physics",
    "domain_pack", "domain_authority", "meta_authority", "policy_gate", "hash_chain",
    "rbac", "domain_registry", "standing_order", "escalation", "daemon_batch",
    "tool_adapter", "domain_lib", "pseudonymous_id", "ingestion_pipeline",
    "governed_modules", "invite_token", "pending_user",
])


def extract_glossary_match(
    input_text: str,
    glossary_terms: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Match known glossary terms in the input text.

    Returns
    -------
    dict
        ``glossary_terms_matched`` (list[str]).
    """
    terms = glossary_terms if glossary_terms is not None else _SYSTEM_GLOSSARY
    lower = input_text.lower()
    matched = [t for t in terms if t in lower or t.replace("_", " ") in lower]
    return {"glossary_terms_matched": matched}


# ── Main entry point ─────────────────────────────────────────────────────────

def nlp_preprocess(input_text: str, task_context: dict[str, Any]) -> dict[str, Any]:
    """Run all NLP extractors and return a partial evidence dict.

    Parameters
    ----------
    input_text : str
        Raw operator message.
    task_context : dict
        Current task context (may contain ``glossary_terms`` for term override).

    Returns
    -------
    dict
        Partial evidence dict with ``_nlp_anchors`` metadata list.
    """
    glossary_terms: frozenset[str] | None = None
    raw_terms = task_context.get("glossary_terms")
    if raw_terms:
        glossary_terms = frozenset(raw_terms)

    verb_result = extract_admin_verb(input_text)
    user_result = extract_target_user(input_text)
    role_result = extract_target_role(input_text)
    compound_result = detect_compound_command(input_text)
    glossary_result = extract_glossary_match(input_text, glossary_terms)

    evidence: dict[str, Any] = {}
    anchors: list[dict[str, Any]] = []

    # Admin verb intent
    if verb_result["intent_type"] != "unknown":
        evidence["intent_type"] = verb_result["intent_type"]
        anchor: dict[str, Any] = {
            "field": "intent_type",
            "value": verb_result["intent_type"],
            "confidence": verb_result["confidence"],
        }
        if verb_result["verb"]:
            anchor["detail"] = f"verb: {verb_result['verb']}"
        anchors.append(anchor)

    # Target user
    if user_result["target_user"] is not None:
        evidence["target_user"] = user_result["target_user"]
        anchors.append({
            "field": "target_user",
            "value": user_result["target_user"],
            "confidence": user_result["confidence"],
        })

    # Target role
    if role_result["target_role"] is not None:
        evidence["target_role"] = role_result["target_role"]
        role_anchor: dict[str, Any] = {
            "field": "target_role",
            "value": role_result["target_role"],
            "confidence": role_result["confidence"],
        }
        if role_result["governed_domains"]:
            role_anchor["detail"] = f"governed_domains: {role_result['governed_domains']}"
        anchors.append(role_anchor)

    # Glossary matches
    if glossary_result["glossary_terms_matched"]:
        evidence["glossary_terms_matched"] = glossary_result["glossary_terms_matched"]
        anchors.append({
            "field": "glossary_terms_matched",
            "value": glossary_result["glossary_terms_matched"],
            "confidence": 1.0,
            "detail": ", ".join(glossary_result["glossary_terms_matched"]),
        })

    # Compound command (informational)
    if compound_result["is_compound"]:
        evidence["is_compound_command"] = True
        anchors.append({
            "field": "compound_command",
            "value": True,
            "confidence": 0.85,
            "detail": (
                f"estimated {compound_result['operation_count_estimate']} operations"
                " — pick the single most specific mutation"
            ),
        })

    evidence["_nlp_anchors"] = anchors
    return evidence
