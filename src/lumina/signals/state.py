"""lumina.signals.state — Dataclasses for the signal decomposition framework.

These types are the lingua franca for the framework. They're intentionally
minimal — the daemon and the per-turn adapter both build them from the
domain's declared signal definitions.

Shape contract for ``SignalBaseline.per_signal[<name>]`` (in-memory dict):

    {
        "ewma": float,
        "variance": float,
        "prev_ewma": float,
        "crossing_rate": float,         # 0..1, EWMA of "did residual flip sign?"
        "run_length": int,              # signed; +N consecutive up, -N consecutive down
        "sample_count": int,
        "spectral_history": dict,       # populated only by the daemon (FFT path)
    }

Persistence shape (round-trippable through ``to_dict``/``from_dict``)
matches this 1:1 — the framework owns it end to end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────
# Defaults — chosen to match the historical SVA seeding so the
# assistant adapter migrates with zero behaviour change.
# ─────────────────────────────────────────────────────────────

DEFAULT_VARIANCE_SEED: float = 0.04
DEFAULT_CROSSING_RATE_SEED: float = 0.5


@dataclass
class SignalSample:
    """A single observation of a named signal at a point in time.

    ``ts`` is an ISO-8601 UTC timestamp (string) — the framework never
    parses naive datetimes. ``value`` is a real-valued scalar; range
    bounds (if any) live in the domain's signal definition, not here.
    """

    name: str
    value: float
    ts: str


@dataclass
class SignalBaseline:
    """Per-signal EWMA baselines for a single actor (or other tracked entity).

    The container is keyed by signal name. Each value follows the
    ``per_signal[<name>]`` shape documented at the top of this module.
    The framework treats unknown signals as new — first observation
    seeds them at the observed value.
    """

    per_signal: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise. Per-signal entries are already plain dicts; round
        floats for stability across snapshot diffs."""
        out: dict[str, Any] = {}
        for name, entry in self.per_signal.items():
            out[name] = {
                "ewma": round(float(entry.get("ewma", 0.0)), 6),
                "variance": round(float(entry.get("variance", DEFAULT_VARIANCE_SEED)), 6),
                "prev_ewma": round(float(entry.get("prev_ewma", entry.get("ewma", 0.0))), 6),
                "crossing_rate": round(float(entry.get("crossing_rate", DEFAULT_CROSSING_RATE_SEED)), 6),
                "run_length": int(entry.get("run_length", 0)),
                "sample_count": int(entry.get("sample_count", 0)),
                "spectral_history": dict(entry.get("spectral_history") or {}),
            }
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SignalBaseline":
        if not data:
            return cls()
        per: dict[str, dict[str, Any]] = {}
        for name, entry in data.items():
            if not isinstance(entry, dict):
                continue
            per[name] = {
                "ewma": float(entry.get("ewma", 0.0)),
                "variance": float(entry.get("variance", DEFAULT_VARIANCE_SEED)),
                "prev_ewma": float(entry.get("prev_ewma", entry.get("ewma", 0.0))),
                "crossing_rate": float(entry.get("crossing_rate", DEFAULT_CROSSING_RATE_SEED)),
                "run_length": int(entry.get("run_length", 0)),
                "sample_count": int(entry.get("sample_count", 0)),
                "spectral_history": dict(entry.get("spectral_history") or {}),
            }
        return cls(per_signal=per)


@dataclass
class SignalDriftSignal:
    """Velocity / fast-drift result for a single signal.

    ``magnitude`` is ``|ewma - prev_ewma|``. ``is_fast_drift`` is True
    when ``magnitude`` exceeds the per-signal fast-drift threshold and
    the baseline has matured past its ``min_samples`` gate.
    """

    name: str
    velocity: float = 0.0
    magnitude: float = 0.0
    is_fast_drift: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "velocity": round(float(self.velocity), 6),
            "magnitude": round(float(self.magnitude), 6),
            "is_fast_drift": bool(self.is_fast_drift),
        }
