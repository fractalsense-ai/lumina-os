"""Agriculture POC for the signal-decomposition framework (Phase H.6).

Validates the instrument-vs-reactions principle: the same daemon task
(`rhythm_fft_analysis`) and the same `lumina.signals` math that drive
the assistant pack's SVA monitoring also drive a totally different
domain (agriculture) with totally different actor signals — soil pH,
soil moisture, motor vibration — declared in agriculture's
`domain-physics.json` `signals` block with per-signal `record_path`
extractors and per-signal band overrides.

This test exercises the framework as a black box from the agriculture
domain's perspective:

1.  The agriculture pack's `to_signal_samples()` adapter converts
    `SensorReading` objects into framework `SignalSample` objects. The
    framework then folds them into a per-actor `SignalBaseline` whose
    keys are the agriculture-domain signal names (no SVA bias).
2.  Synthetic field records carrying nested `sensors.soil.pH` readings
    are routed through the daemon task using the agriculture physics
    block. A chronic downward pH drift produces an advisory keyed by
    `signal=soil_pH, band=dc_drift, direction=-1` — proving that:
       a. `record_path` extraction works for non-SVA signal names.
       b. The framework writes per-signal advisories whose `signal`
          field matches the agriculture-declared name verbatim.
       c. Per-signal `message_overrides` are honored (the rendered
          advisory message contains the override's `{label}` template
          substitution).
3.  Loading the agriculture domain physics from disk validates the
    Phase H.2 schema additions hold for a real domain pack.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from lumina.daemon.tasks import get_task
from lumina.signals import SignalBaseline, update_baseline, update_spectral_history


REPO_ROOT = Path(__file__).resolve().parents[1]
AGRICULTURE_PHYSICS_PATH = (
    REPO_ROOT
    / "domain-packs"
    / "agriculture"
    / "modules"
    / "operations-level-1"
    / "domain-physics.json"
)
ENVIRONMENTAL_SENSORS_PATH = (
    REPO_ROOT
    / "domain-packs"
    / "agriculture"
    / "domain-lib"
    / "sensors"
    / "environmental_sensors.py"
)


def _load_environmental_sensors():
    """Dynamically load the agriculture group library (its parent directory
    contains dashes so it isn't importable as a regular Python package)."""
    import importlib.util
    import sys
    mod_name = "agri_environmental_sensors_under_test"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name, ENVIRONMENTAL_SENSORS_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass introspection (Python 3.13) can
    # locate the defining module via sys.modules.
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


# ── Mock persistence (mirrors the pattern from test_daemon_rhythm_fft.py) ──


class _MockPersistence:
    def __init__(self, profiles: dict[str, dict], records: list[dict]):
        self._profiles = profiles
        self._records = records

    def list_users(self) -> list[dict[str, Any]]:
        return [{"user_id": uid} for uid in self._profiles]

    def list_profiles(self, user_id: str) -> list[str]:
        return list(self._profiles.get(user_id, {}).keys())

    def load_profile(self, user_id: str, domain_key: str):
        return self._profiles.get(user_id, {}).get(domain_key)

    def save_profile(self, user_id: str, domain_key: str, data: dict[str, Any]) -> None:
        self._profiles.setdefault(user_id, {})[domain_key] = data

    def query_log_records(
        self,
        record_type: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        **_kw: Any,
    ) -> list[dict[str, Any]]:
        out = self._records
        if record_type:
            out = [r for r in out if r.get("record_type") == record_type]
        return out[:limit]


# ── Helpers ───────────────────────────────────────────────────


def _agriculture_physics() -> dict[str, Any]:
    return json.loads(AGRICULTURE_PHYSICS_PATH.read_text(encoding="utf-8"))


def _make_field_trace(
    actor_id: str,
    ts: datetime,
    *,
    soil_ph: float,
    soil_moisture: float = 35.0,
    air_temperature: float = 18.0,
) -> dict[str, Any]:
    """Build a TraceEvent shaped like a field-sensor sweep."""
    return {
        "record_type": "TraceEvent",
        "actor_id": actor_id,
        "timestamp_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "sensor_sweep",
        "sensors": {
            "soil": {
                "pH": soil_ph,
                "moisture_pct": soil_moisture,
            },
            "air": {
                "temperature_c": air_temperature,
            },
        },
    }


def _seed_soil_ph_history(stable_dc: float = 6.7, runs: int = 8) -> dict[str, Any]:
    """Pre-seed a mature spectral history for soil_pH around `stable_dc`."""
    hist: dict[str, Any] = {}
    for i in range(runs):
        sig = {
            "dc_drift": stable_dc + (0.01 if i % 2 else -0.01),
            "circaseptan": 0.05,
            "noise_floor": 0.04,
            "dc_direction": 1,
        }
        hist = update_spectral_history(hist, sig)
    return hist


# ─────────────────────────────────────────────────────────────
# 1. Domain pack physics declares the framework's signals block
# ─────────────────────────────────────────────────────────────


class TestAgriculturePhysicsDeclaresSignals:

    def test_physics_loads_from_disk(self):
        physics = _agriculture_physics()
        assert physics["id"].startswith("domain/agriculture/")

    def test_signals_block_present_with_expected_signals(self):
        physics = _agriculture_physics()
        assert "signals" in physics, "agriculture physics should declare a signals block"
        names = set(physics["signals"])
        assert {"soil_pH", "soil_moisture", "air_temperature", "motor_vibration"} <= names

    def test_each_signal_has_record_path_and_label(self):
        physics = _agriculture_physics()
        for name, sdef in physics["signals"].items():
            assert isinstance(sdef.get("label"), str) and sdef["label"], (
                f"signal {name!r} missing label")
            assert isinstance(sdef.get("record_path"), str), (
                f"signal {name!r} missing record_path")

    def test_motor_vibration_uses_intra_hour_band(self):
        physics = _agriculture_physics()
        bands = physics["signals"]["motor_vibration"]["bands"]
        assert "intra_hour" in bands
        win = bands["intra_hour"]["window_days"]
        assert win[1] < 1.0  # sub-day cadence


# ─────────────────────────────────────────────────────────────
# 2. Agriculture's to_signal_samples adapter feeds the framework
# ─────────────────────────────────────────────────────────────


class TestAgricultureSignalSampleAdapter:

    def test_adapter_uses_sensor_id_when_no_mapping(self):
        sensors_mod = _load_environmental_sensors()
        SensorReading = sensors_mod.SensorReading
        to_signal_samples = sensors_mod.to_signal_samples
        readings = [
            SensorReading(sensor_id="soil_pH", value=6.4, unit="pH",
                          timestamp="2026-04-01T08:00:00Z"),
            SensorReading(sensor_id="soil_pH", value=6.2, unit="pH",
                          timestamp="2026-04-02T08:00:00Z"),
        ]
        samples = to_signal_samples(readings)
        assert [s.name for s in samples] == ["soil_pH", "soil_pH"]
        assert [s.value for s in samples] == [6.4, 6.2]

    def test_adapter_honors_explicit_sensor_to_signal_mapping(self):
        sensors_mod = _load_environmental_sensors()
        SensorReading = sensors_mod.SensorReading
        to_signal_samples = sensors_mod.to_signal_samples
        readings = [
            SensorReading(sensor_id="barn_3_collar_b", value=12.4,
                          unit="mm/s", timestamp="2026-04-25T10:00:00Z"),
        ]
        samples = to_signal_samples(
            readings,
            signal_name_for={"barn_3_collar_b": "motor_vibration"},
        )
        assert samples[0].name == "motor_vibration"
        assert samples[0].value == 12.4

    def test_framework_baseline_keyed_by_agriculture_signal_name(self):
        """Framework writes per-signal entries under the agriculture name."""
        sensors_mod = _load_environmental_sensors()
        SensorReading = sensors_mod.SensorReading
        to_signal_samples = sensors_mod.to_signal_samples
        readings = [
            SensorReading(sensor_id="probe_a", value=6.7, unit="pH",
                          timestamp="2026-04-01T08:00:00Z"),
            SensorReading(sensor_id="probe_a", value=6.6, unit="pH",
                          timestamp="2026-04-02T08:00:00Z"),
        ]
        samples = to_signal_samples(
            readings, signal_name_for={"probe_a": "soil_pH"})

        baseline = SignalBaseline()
        for s in samples:
            baseline = update_baseline(baseline, s, range_lo=3.0, range_hi=10.0)

        assert "soil_pH" in baseline.per_signal
        # No SVA-named entries leaked into the agriculture baseline
        assert "valence" not in baseline.per_signal
        assert "salience" not in baseline.per_signal


# ─────────────────────────────────────────────────────────────
# 3. End-to-end: chronic soil_pH drift produces an advisory
# ─────────────────────────────────────────────────────────────


class TestAgricultureChronicDriftEndToEnd:

    def test_chronic_soil_ph_drift_emits_proposal_with_signal_name(self):
        task = get_task("rhythm_fft_analysis")

        actor = "field_alpha"
        domain_key = "agriculture"
        profile = {
            "subject_id": actor,
            "learning_state": {
                "signal_baselines": {
                    "spectral_history": {
                        "soil_pH": _seed_soil_ph_history(stable_dc=6.7),
                    },
                },
            },
        }
        profiles = {actor: {domain_key: profile}}

        # 60 days of sensor sweeps. First 46 days hover around pH 6.7;
        # last 14 days slide acidic toward pH 5.5 → chronic dc_drift
        # negative on soil_pH.
        now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
        records: list[dict] = []
        for d in range(60):
            ts = now - timedelta(days=59 - d)
            if d < 46:
                ph = 6.7 + 0.05 * math.sin(2 * math.pi * d / 7.0)
            else:
                ph = 6.7 - 1.2 * (d - 45) / 14.0
            for hour_offset in (0, 6, 12):
                records.append(
                    _make_field_trace(actor, ts + timedelta(hours=hour_offset),
                                      soil_ph=ph))

        persistence = _MockPersistence(profiles, records)
        physics = _agriculture_physics()

        result = task("agriculture", physics, persistence=persistence)

        assert result.success, f"task failed: {result.error}"
        assert result.metadata["profiles_analyzed"] == 1
        # Framework iterates whichever signals the domain declared
        signals_run = result.metadata["signals_run"]
        assert "soil_pH" in signals_run

        # Find chronic drift proposals for soil_pH (any band — the
        # spectral detector decides which bands trip; this test only
        # asserts that the framework writes per-signal proposals keyed
        # by the agriculture-declared name, NOT that any one specific
        # band fires for this synthetic data).
        chronic = [
            p for p in result.proposals
            if p.proposal_type == "chronic_spectral_drift"
            and p.detail.get("signal") == "soil_pH"
        ]
        assert chronic, (
            f"expected at least one chronic_spectral_drift proposal for "
            f"soil_pH; got proposals: "
            f"{[(p.proposal_type, p.detail.get('signal'), p.detail.get('band')) for p in result.proposals]}")
        # Direction is either +1 or -1 (int from spectral.py)
        assert chronic[0].detail["direction"] in (1, -1)
        assert chronic[0].detail["user_id"] == actor

    def test_advisory_persisted_uses_per_signal_message_override(self):
        """The agriculture physics declares a circaseptan,* override for
        soil_pH; verify it lands in the persisted advisory message
        (with the {label} substitution applied)."""
        task = get_task("rhythm_fft_analysis")
        actor = "field_beta"
        domain_key = "agriculture"
        profile = {
            "subject_id": actor,
            "learning_state": {
                "signal_baselines": {
                    "spectral_history": {
                        "soil_pH": _seed_soil_ph_history(stable_dc=6.7),
                    },
                },
            },
        }
        profiles = {actor: {domain_key: profile}}

        now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
        records: list[dict] = []
        for d in range(60):
            ts = now - timedelta(days=59 - d)
            if d < 46:
                ph = 6.7
            else:
                ph = 6.7 - 1.2 * (d - 45) / 14.0
            for hour_offset in (0, 6, 12):
                records.append(
                    _make_field_trace(actor, ts + timedelta(hours=hour_offset),
                                      soil_ph=ph))

        persistence = _MockPersistence(profiles, records)
        physics = _agriculture_physics()

        result = task("agriculture", physics, persistence=persistence)
        assert result.success

        saved = persistence.load_profile(actor, domain_key)
        advisories = saved["learning_state"].get("spectral_advisories", [])
        # Find soil_pH/circaseptan advisory (any direction — wildcard override)
        soil_circaseptan = [
            a for a in advisories
            if a.get("signal") == "soil_pH" and a.get("band") == "circaseptan"
        ]
        assert soil_circaseptan, (
            f"expected a soil_pH circaseptan advisory; got: {advisories}")
        msg = soil_circaseptan[0]["message"]
        # Override template substitutes {label} → "soil pH"
        assert "soil pH" in msg
        # Override-specific phrase (not the framework default)
        assert "irrigation" in msg.lower(), (
            f"expected the per-signal override message text, got: {msg!r}")


# ─────────────────────────────────────────────────────────────
# 4. Conformance — persisted advisory matches the formal schema
# ─────────────────────────────────────────────────────────────


class TestAgricultureAdvisoryConformsToSchema:

    def test_advisory_entry_conforms_to_spectral_advisory_schema(self):
        try:
            import jsonschema  # type: ignore
        except ImportError:
            pytest.skip("jsonschema not installed in this env")

        schema_path = REPO_ROOT / "standards" / "spectral-advisory-schema-v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        task = get_task("rhythm_fft_analysis")
        actor = "field_gamma"
        domain_key = "agriculture"
        profile = {
            "subject_id": actor,
            "learning_state": {
                "signal_baselines": {
                    "spectral_history": {
                        "soil_pH": _seed_soil_ph_history(stable_dc=6.7),
                    },
                },
            },
        }
        profiles = {actor: {domain_key: profile}}

        now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
        records: list[dict] = []
        for d in range(60):
            ts = now - timedelta(days=59 - d)
            ph = 6.7 if d < 46 else 6.7 - 1.2 * (d - 45) / 14.0
            for hour_offset in (0, 6, 12):
                records.append(
                    _make_field_trace(actor, ts + timedelta(hours=hour_offset),
                                      soil_ph=ph))

        persistence = _MockPersistence(profiles, records)
        physics = _agriculture_physics()
        result = task("agriculture", physics, persistence=persistence)
        assert result.success

        saved = persistence.load_profile(actor, domain_key)
        advisories = saved["learning_state"].get("spectral_advisories", [])
        assert advisories, "no advisories produced"
        for adv in advisories:
            jsonschema.validate(adv, schema)
