"""Environmental sensor normalization library for the agriculture domain.

Provides shared signal-processing utilities used by multiple modules
(operations-level-1 and future modules like crop-planning, livestock, etc.).
This is a Group Library — pure functions, no LLM involvement, deterministic
when given the same inputs.

Conforms to the domain-state-lib contract:
    - Deterministic: same inputs → same output
    - Structured I/O: dict in, dict out
    - No free text processing, no external dependencies
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ── Data Structures ───────────────────────────────────────────


@dataclass
class SensorReading:
    """A single normalized sensor reading."""

    sensor_id: str
    value: float
    unit: str
    timestamp: str  # ISO-8601
    quality: float = 1.0  # 0..1 confidence in reading


@dataclass
class ToleranceBand:
    """Acceptable operating range for a sensor signal."""

    lower: float
    upper: float
    unit: str


# ── Normalization ─────────────────────────────────────────────


def normalize_reading(
    raw_value: float,
    band: ToleranceBand,
) -> float:
    """Normalize a raw sensor value to 0..1 within the tolerance band.

    Returns 0.0 at band.lower, 1.0 at band.upper.
    Values outside the band are clamped.
    """
    span = band.upper - band.lower
    if span <= 0:
        return 0.5
    return max(0.0, min(1.0, (raw_value - band.lower) / span))


def check_within_tolerance(
    reading: SensorReading,
    band: ToleranceBand,
) -> dict[str, Any]:
    """Check whether a sensor reading is within the acceptable tolerance band.

    Returns a dict with:
        within_tolerance: bool
        normalized_value: float (0..1)
        deviation: float (signed distance from nearest band edge, 0 if within)
    """
    normalized = normalize_reading(reading.value, band)
    within = band.lower <= reading.value <= band.upper

    if reading.value < band.lower:
        deviation = reading.value - band.lower
    elif reading.value > band.upper:
        deviation = reading.value - band.upper
    else:
        deviation = 0.0

    return {
        "within_tolerance": within,
        "normalized_value": normalized,
        "deviation": deviation,
        "sensor_id": reading.sensor_id,
        "quality": reading.quality,
    }


def aggregate_readings(
    readings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute summary statistics over a batch of tolerance-check results.

    Parameters
    ----------
    readings : list of dicts returned by check_within_tolerance()

    Returns
    -------
    dict with count, within_count, outside_count, mean_normalized, min_quality.
    """
    if not readings:
        return {
            "count": 0,
            "within_count": 0,
            "outside_count": 0,
            "mean_normalized": 0.0,
            "min_quality": 0.0,
        }

    within_count = sum(1 for r in readings if r.get("within_tolerance"))
    normalized_values = [r.get("normalized_value", 0.0) for r in readings]
    qualities = [r.get("quality", 1.0) for r in readings]

    return {
        "count": len(readings),
        "within_count": within_count,
        "outside_count": len(readings) - within_count,
        "mean_normalized": sum(normalized_values) / len(normalized_values),
        "min_quality": min(qualities),
    }
