"""lumina.signals.templates — Advisory message rendering.

The framework provides a generic message template keyed by ``(band, direction)``
plus a hook for per-signal overrides. Domain packs supply overrides via the
``message_overrides`` map on their signal definition (declared in
``domain-physics.json``). Override keys follow the format
``"<band>,<direction>"`` or ``"<band>,*"`` (wildcard direction).

Generic fallback templates are deliberately neutral — they describe a
shifted pattern in plain language without injecting any clinical or
domain-specific framing. Domains that need more nuanced phrasing (e.g.
"your overall mood has been drifting downward") supply overrides.
"""

from __future__ import annotations

from typing import Any

# ─────────────────────────────────────────────────────────────
# Framework defaults — keyed by (band, direction). Direction
# may be "positive", "negative", or "*" (wildcard match).
# ─────────────────────────────────────────────────────────────

_DEFAULT_BAND_DIRECTION_TEMPLATES: dict[tuple[str, str], str] = {
    ("dc_drift", "positive"):
        "{label} has been drifting upward over the recent window.",
    ("dc_drift", "negative"):
        "{label} has been drifting downward over the recent window.",
    ("dc_drift", "*"):
        "A slow chronic shift has been detected on {label}.",
    ("circaseptan", "*"):
        "A weekly cyclic pattern on {label} has shifted noticeably.",
    ("ultradian", "*"):
        "Multi-day swings on {label} have become more pronounced.",
}


def _lookup(
    table: dict[Any, str],
    band: str,
    direction: str,
) -> str | None:
    if (band, direction) in table:
        return table[(band, direction)]
    if (band, "*") in table:
        return table[(band, "*")]
    return None


def _normalise_overrides(
    overrides: dict[str, str] | None,
) -> dict[tuple[str, str], str]:
    """Convert ``"<band>,<direction>"`` keys into tuple keys for lookup."""
    out: dict[tuple[str, str], str] = {}
    if not overrides:
        return out
    for key, msg in overrides.items():
        if not isinstance(key, str) or not isinstance(msg, str):
            continue
        if "," not in key:
            continue
        band, direction = key.split(",", 1)
        out[(band.strip(), direction.strip())] = msg
    return out


def render_advisory_message(
    signal_label: str,
    band: str,
    direction: str,
    *,
    signal_overrides: dict[str, str] | None = None,
) -> str:
    """Render a human-readable advisory message.

    Lookup order:
        1. ``signal_overrides[(band, direction)]`` (per-signal exact match)
        2. ``signal_overrides[(band, "*")]`` (per-signal wildcard direction)
        3. Framework default for ``(band, direction)``
        4. Framework wildcard ``(band, "*")``
        5. Generic fallback string

    The ``{label}`` token in any template is substituted with
    ``signal_label`` so per-signal overrides can stay direction-only.
    """
    direction_norm = direction or "*"
    label = signal_label or "this signal"

    overrides_map = _normalise_overrides(signal_overrides)
    template = (
        _lookup(overrides_map, band, direction_norm)
        or _lookup(_DEFAULT_BAND_DIRECTION_TEMPLATES, band, direction_norm)
        or f"A chronic {band} pattern has shifted on {{label}}."
    )
    try:
        return template.format(label=label)
    except (KeyError, IndexError, ValueError):
        # Override author used unknown placeholder; return raw template
        # rather than crashing the daemon.
        return template
