"""lumina.signals.advisories — Spectral advisory upsert + retrieval.

Domain-agnostic equivalent of the bespoke advisory plumbing previously
wired into ``src/lumina/daemon/tasks.py`` and
``model-packs/education/controllers/journal_adapters.py``.

Persisted advisory dict shape (lives on
``profile.learning_state.spectral_advisories``):

    {
        "advisory_id":   str (uuid),
        "signal":        str   (e.g. "valence", "soil_pH"),
        "band":          str   (e.g. "dc_drift", "circaseptan"),
        "direction":     str   ("positive" | "negative" | "*")
        "z_score":       float,
        "message":       str,
        "created_utc":   ISO-8601 str,
        "expires_utc":   ISO-8601 str,
    }
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_ADVISORY_TTL_SECONDS: int = 24 * 3600


# ─────────────────────────────────────────────────────────────
# Upsert
# ─────────────────────────────────────────────────────────────


def upsert_spectral_advisory(
    advisories: list[dict[str, Any]] | None,
    *,
    signal: str,
    band: str,
    finding: dict[str, Any],
    message: str,
    now_utc: datetime | None = None,
    ttl_seconds: int = DEFAULT_ADVISORY_TTL_SECONDS,
) -> list[dict[str, Any]]:
    """Insert/replace an advisory keyed by ``(signal, band)``.

    Returns a NEW list (does not mutate input). Same-key entries are
    evicted; expired entries are pruned. ``message`` is supplied by the
    caller (typically via ``render_advisory_message``) so the framework
    stays free of presentation logic.
    """
    now = now_utc or datetime.now(timezone.utc)
    expires = now + timedelta(seconds=int(ttl_seconds))
    direction = str(finding.get("direction", "neutral"))
    new_entry = {
        "advisory_id": str(uuid.uuid4()),
        "signal": signal,
        "band": band,
        "direction": direction,
        "z_score": float(finding.get("z_score", 0.0)),
        "message": message,
        "created_utc": now.isoformat(),
        "expires_utc": expires.isoformat(),
    }
    out: list[dict[str, Any]] = []
    for adv in advisories or []:
        if not isinstance(adv, dict):
            continue
        if adv.get("signal") == signal and adv.get("band") == band:
            continue
        exp = adv.get("expires_utc")
        if isinstance(exp, str):
            try:
                if datetime.fromisoformat(exp) <= now:
                    continue
            except ValueError:
                continue
        out.append(adv)
    out.append(new_entry)
    return out


# ─────────────────────────────────────────────────────────────
# Active-advisory retrieval (consumer side)
# ─────────────────────────────────────────────────────────────


def pull_active_advisory(
    advisories: list[dict[str, Any]] | None,
    *,
    signal_priority: tuple[str, ...] | list[str] | None = None,
    band_priority: tuple[str, ...] | list[str] | None = None,
    now_utc: datetime | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return ``(highest-priority active advisory | None, pruned list)``.

    Pruning drops expired entries; the returned ``pruned list`` is what
    callers should write back to disk. Priority ordering: lower index
    = higher priority. Unknown signals/bands rank after all known ones.

    When both priority tuples are empty/None, we fall back to most-recent
    ``created_utc``.
    """
    if not advisories:
        return None, []

    now = now_utc or datetime.now(timezone.utc)
    sig_pri = tuple(signal_priority or ())
    band_pri = tuple(band_priority or ())

    surviving: list[dict[str, Any]] = []
    for adv in advisories:
        if not isinstance(adv, dict):
            continue
        exp = adv.get("expires_utc")
        if isinstance(exp, str):
            try:
                if datetime.fromisoformat(exp) <= now:
                    continue
            except ValueError:
                continue
        surviving.append(adv)

    if not surviving:
        return None, surviving

    def _rank(a: dict[str, Any]) -> tuple[int, int, str]:
        sig = str(a.get("signal", ""))
        bd = str(a.get("band", ""))
        s_rank = sig_pri.index(sig) if sig in sig_pri else len(sig_pri)
        b_rank = band_pri.index(bd) if bd in band_pri else len(band_pri)
        # Tie-break by negative created_utc — newer wins. We invert by
        # using the inverse string sort when both ranks are equal.
        return (s_rank, b_rank, str(a.get("created_utc", "")))

    if not sig_pri and not band_pri:
        # Pure most-recent fallback
        best = max(surviving, key=lambda a: str(a.get("created_utc", "")))
    else:
        # Min by rank; break ties toward newer created_utc.
        best = min(surviving, key=lambda a: (_rank(a)[0], _rank(a)[1],
                                             # invert created_utc for tie-break
                                             tuple(-ord(c) for c in str(a.get("created_utc", "")))))

    return best, surviving
