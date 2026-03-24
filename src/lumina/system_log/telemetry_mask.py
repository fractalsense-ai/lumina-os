"""
telemetry_mask.py — Field-Level Telemetry Masking

Pure-function masking layer that transforms :class:`LogEvent` payloads
before they reach log-bus subscribers.  Strategies:

* **pass**            — no transformation.
* **sha256_hash**     — one-way SHA-256 digest of the string value.
* **hmac_pseudonym**  — keyed HMAC-SHA256 producing a stable pseudonym
                        (reversible only with the key; same input always
                        yields the same output within a key epoch).
* **redact**          — replace with ``"[REDACTED]"``.
* **truncate**        — keep the first *N* characters, pad with ``"…"``.

The masking policy is a list of :class:`FieldRule` objects evaluated
top-to-bottom; first match wins.  Wildcard paths (``*`` for a single
segment, ``**`` for recursive) are supported.

Toggle at runtime via ``LUMINA_TELEMETRY_MASKING_ENABLED`` (default off).
HMAC key is read from ``LUMINA_TELEMETRY_HMAC_KEY`` — if absent the
``hmac_pseudonym`` strategy falls back to ``sha256_hash``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from typing import Any

from lumina.system_log.event_payload import LogEvent

log = logging.getLogger("lumina.telemetry-mask")


# ── Configuration ─────────────────────────────────────────────

def _masking_enabled() -> bool:
    return os.environ.get(
        "LUMINA_TELEMETRY_MASKING_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes"}


def _hmac_key() -> bytes | None:
    raw = os.environ.get("LUMINA_TELEMETRY_HMAC_KEY")
    if raw:
        return raw.encode("utf-8")
    return None


# ── Data model ────────────────────────────────────────────────

class Sensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class Strategy(str, Enum):
    PASS = "pass"
    SHA256_HASH = "sha256_hash"
    HMAC_PSEUDONYM = "hmac_pseudonym"
    REDACT = "redact"
    TRUNCATE = "truncate"


@dataclass(frozen=True, slots=True)
class FieldRule:
    """A single masking rule matching a dot-path pattern."""

    path: str
    sensitivity: Sensitivity
    strategy: Strategy
    truncate_length: int | None = None


@dataclass
class MaskingPolicy:
    """Ordered rule set evaluated top-to-bottom; first match wins."""

    rules: list[FieldRule] = field(default_factory=list)
    default_strategy: Strategy = Strategy.PASS


# ── Path matching ─────────────────────────────────────────────

# Compile path patterns to fnmatch-style: dots become path separators.
# "data.*.email" matches "data.foo.email" but not "data.foo.bar.email".
# "data.**.email" matches both.

def _path_matches(pattern: str, path: str) -> bool:
    """Match a dot-path against a pattern supporting ``*`` and ``**``."""
    # Convert ** to a sentinel, then split
    pat_parts = pattern.split(".")
    path_parts = path.split(".")
    return _match_parts(pat_parts, path_parts)


def _match_parts(pat: list[str], path: list[str]) -> bool:
    """Recursive glob-style match on path segments."""
    pi = 0
    pj = 0
    while pi < len(pat) and pj < len(path):
        if pat[pi] == "**":
            # ** consumes zero or more segments
            if pi + 1 == len(pat):
                return True  # trailing ** matches everything
            # Try matching the rest of the pattern from every position
            for k in range(pj, len(path) + 1):
                if _match_parts(pat[pi + 1:], path[k:]):
                    return True
            return False
        elif fnmatch(path[pj], pat[pi]):
            pi += 1
            pj += 1
        else:
            return False
    # Consume trailing ** patterns
    while pi < len(pat) and pat[pi] == "**":
        pi += 1
    return pi == len(pat) and pj == len(path)


# ── Strategy implementations ──────────────────────────────────

def _apply_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _apply_hmac(value: str, key: bytes) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _apply_redact(_value: str) -> str:
    return "[REDACTED]"


def _apply_truncate(value: str, length: int) -> str:
    if len(value) <= length:
        return value
    return value[:length] + "…"


def _mask_value(value: Any, strategy: Strategy, rule: FieldRule, key: bytes | None) -> Any:
    """Apply a masking strategy to a single value."""
    if strategy == Strategy.PASS:
        return value
    # Only mask string values; non-strings get redacted to be safe.
    s = str(value)
    if strategy == Strategy.SHA256_HASH:
        return _apply_sha256(s)
    if strategy == Strategy.HMAC_PSEUDONYM:
        if key is not None:
            return _apply_hmac(s, key)
        log.warning(
            "HMAC key not set — falling back to sha256_hash for path '%s'",
            rule.path,
        )
        return _apply_sha256(s)
    if strategy == Strategy.REDACT:
        return _apply_redact(s)
    if strategy == Strategy.TRUNCATE:
        return _apply_truncate(s, rule.truncate_length or 8)
    return value  # pragma: no cover — exhaustive enum


# ── Core masking function (pure) ──────────────────────────────

def _find_rule(policy: MaskingPolicy, path: str) -> Strategy | None:
    """Return the strategy of the first matching rule, or *None*."""
    for rule in policy.rules:
        if _path_matches(rule.path, path):
            return rule.strategy
    return None


def _find_rule_obj(policy: MaskingPolicy, path: str) -> FieldRule | None:
    for rule in policy.rules:
        if _path_matches(rule.path, path):
            return rule
    return None


def _mask_dict(
    d: dict[str, Any],
    policy: MaskingPolicy,
    key: bytes | None,
    prefix: str,
) -> dict[str, Any]:
    """Recursively walk a dict applying matching rules."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        rule = _find_rule_obj(policy, path)
        if rule is not None:
            # Explicit rule matched — apply its strategy (including PASS).
            if rule.strategy == Strategy.PASS:
                out[k] = v
            elif isinstance(v, dict):
                # Rule targets a dict subtree — mask the whole thing.
                out[k] = _mask_value(str(v), rule.strategy, rule, key)
            else:
                out[k] = _mask_value(v, rule.strategy, rule, key)
        elif isinstance(v, dict):
            out[k] = _mask_dict(v, policy, key, path)
        elif policy.default_strategy != Strategy.PASS:
            # No rule matched — apply default strategy.
            dummy_rule = FieldRule(
                path=path,
                sensitivity=Sensitivity.INTERNAL,
                strategy=policy.default_strategy,
            )
            out[k] = _mask_value(v, policy.default_strategy, dummy_rule, key)
        else:
            out[k] = v
    return out


def mask_event(event: LogEvent, policy: MaskingPolicy) -> LogEvent:
    """Return a new LogEvent with sensitive fields masked per *policy*.

    This is a **pure function** — the original event is not mutated.
    The ``record`` field (hash-chained audit data) is **never masked**
    because it is cryptographically committed; masking would break the
    hash chain.
    """
    key = _hmac_key()

    masked_data = _mask_dict(event.data, policy, key, "data")

    # Mask top-level string fields if rules exist.
    source = event.source
    message = event.message
    category = event.category

    for top_field, attr in [("source", source), ("message", message), ("category", category)]:
        rule = _find_rule_obj(policy, top_field)
        if rule is not None and rule.strategy != Strategy.PASS:
            val = _mask_value(attr, rule.strategy, rule, key)
            if top_field == "source":
                source = val
            elif top_field == "message":
                message = val
            elif top_field == "category":
                category = val

    return LogEvent(
        timestamp=event.timestamp,
        source=source,
        level=event.level,
        category=category,
        message=message,
        data=masked_data,
        record=event.record,  # never mask — hash-chain integrity
    )


# ── Policy loader ─────────────────────────────────────────────

def load_policy_from_dict(raw: dict[str, Any]) -> MaskingPolicy:
    """Build a :class:`MaskingPolicy` from a parsed JSON dict."""
    rules: list[FieldRule] = []
    for entry in raw.get("fields", []):
        rules.append(
            FieldRule(
                path=entry["path"],
                sensitivity=Sensitivity(entry["sensitivity"]),
                strategy=Strategy(entry["strategy"]),
                truncate_length=entry.get("truncate_length"),
            )
        )
    default = Strategy(raw.get("default_strategy", "pass"))
    return MaskingPolicy(rules=rules, default_strategy=default)


# ── Singleton policy cache ────────────────────────────────────

_active_policy: MaskingPolicy | None = None


def set_active_policy(policy: MaskingPolicy | None) -> None:
    """Set (or clear) the module-level active masking policy."""
    global _active_policy
    _active_policy = policy


def get_active_policy() -> MaskingPolicy | None:
    """Return the currently active masking policy, if any."""
    return _active_policy


def apply_masking(event: LogEvent) -> LogEvent:
    """Convenience: mask *event* with the active policy if masking is enabled.

    Returns the original event unchanged when:
    - ``LUMINA_TELEMETRY_MASKING_ENABLED`` is not set / falsy, **or**
    - no active policy has been loaded.
    """
    if not _masking_enabled():
        return event
    policy = _active_policy
    if policy is None:
        return event
    return mask_event(event, policy)
