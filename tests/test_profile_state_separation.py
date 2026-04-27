"""Tests for profile state separation, 3-tier init, and SVA baseline tracking.

Covers:
  - Student profile template no longer carries module-specific fields
  - 3-tier state priority in build_initial_learning_state
  - 3-tier state priority in freeform_build_initial_state
  - SVA affect baseline EMA updates
  - Per-module affect signature with delta_from_baseline
  - initial_module_state loaded from runtime-config module entries
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _load_student_yaml() -> dict[str, Any]:
    from lumina.core.yaml_loader import load_yaml

    path = _REPO_ROOT / "model-packs" / "education" / "profiles" / "student.yaml"
    return load_yaml(path)


def _load_runtime_config() -> dict[str, Any]:
    from lumina.core.yaml_loader import load_yaml
    from conftest import merge_module_config_sidecars

    path = _REPO_ROOT / "model-packs" / "education" / "cfg" / "runtime-config.yaml"
    cfg = load_yaml(path)
    module_map = cfg.get("runtime", {}).get("module_map", {})
    merge_module_config_sidecars(module_map)
    return cfg


def _sample_initial_module_state() -> dict[str, Any]:
    """Matches the algebra learning module initial_module_state shape."""
    return {
        "affect": {"salience": 0.5, "valence": 0.0, "arousal": 0.5},
        "mastery": {
            "equivalence_preserved": 0.0,
            "no_illegal_operations": 0.0,
            "solution_verifies": 0.0,
            "show_work_minimum": 0.0,
        },
        "challenge_band": {"min_challenge": 0.3, "max_challenge": 0.7},
        "recent_window": {
            "window_turns": 10,
            "attempts": 0,
            "consecutive_incorrect": 0,
            "hint_count": 0,
            "outside_pct": 0.0,
            "consecutive_outside": 0,
            "outside_flags": [],
            "hint_flags": [],
        },
        "challenge": 0.3,
        "uncertainty": 0.8,
        "fluency": {"current_tier": "tier_1", "consecutive_correct": 0},
    }


def _sample_db_module_state() -> dict[str, Any]:
    """A module state dict as if loaded from the DB (returning student)."""
    return {
        "affect": {"salience": 0.7, "valence": 0.2, "arousal": 0.4},
        "mastery": {
            "equivalence_preserved": 0.6,
            "no_illegal_operations": 0.5,
            "solution_verifies": 0.3,
            "show_work_minimum": 0.2,
        },
        "challenge_band": {"min_challenge": 0.35, "max_challenge": 0.75},
        "recent_window": {
            "window_turns": 10,
            "attempts": 5,
            "consecutive_incorrect": 1,
            "hint_count": 2,
            "outside_pct": 0.1,
            "consecutive_outside": 0,
            "outside_flags": [False, True],
            "hint_flags": [True, False],
        },
        "challenge": 0.45,
        "uncertainty": 0.6,
        "fluency": {"current_tier": "tier_2", "consecutive_correct": 3},
    }


# ─────────────────────────────────────────────────────────────
# 1. Profile template shape
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestStudentProfileTemplate:
    """Verify that the student profile template no longer carries
    module-specific tracking fields."""

    def test_no_module_mastery_key(self) -> None:
        profile = _load_student_yaml()
        assert "module_mastery" not in profile

    def test_no_mastery_in_learning_state(self) -> None:
        ls = _load_student_yaml()["learning_state"]
        assert "mastery" not in ls

    def test_no_challenge_band(self) -> None:
        ls = _load_student_yaml()["learning_state"]
        assert "challenge_band" not in ls

    def test_no_recent_window(self) -> None:
        ls = _load_student_yaml()["learning_state"]
        assert "recent_window" not in ls

    def test_no_fluency(self) -> None:
        ls = _load_student_yaml()["learning_state"]
        assert "fluency" not in ls

    def test_no_top_level_affect(self) -> None:
        ls = _load_student_yaml()["learning_state"]
        assert "affect" not in ls

    def test_has_affect_baseline(self) -> None:
        ls = _load_student_yaml()["learning_state"]
        ab = ls["affect_baseline"]
        assert ab["salience"] == 0.5
        assert ab["valence"] == 0.0
        assert ab["arousal"] == 0.5
        assert ab["sample_count"] == 0
        assert ab["per_module"] == {}

    def test_has_domain_wide_posture(self) -> None:
        ls = _load_student_yaml()["learning_state"]
        assert ls["challenge"] == 0.3
        assert ls["uncertainty"] == 0.8

    def test_has_vocabulary_tracking(self) -> None:
        ls = _load_student_yaml()["learning_state"]
        assert "vocabulary_tracking" in ls
        assert ls["vocabulary_tracking"]["growth_delta"] == 0.0


# ─────────────────────────────────────────────────────────────
# 2. Runtime-config initial_module_state
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRuntimeConfigInitialModuleState:
    """Verify that learning modules declare initial_module_state in
    runtime-config and governance modules do not."""

    _LEARNING_MODULES = [
        "domain/edu/pre-algebra/v1",
        "domain/edu/algebra-intro/v1",
        "domain/edu/algebra-1/v1",
        "domain/edu/algebra-level-1/v1",
    ]

    _GOVERNANCE_MODULES = [
        "domain/edu/domain-authority/v1",
        "domain/edu/teacher/v1",
        "domain/edu/teaching-assistant/v1",
    ]

    def test_learning_modules_have_initial_module_state(self) -> None:
        cfg = _load_runtime_config()
        module_map = cfg["runtime"]["module_map"]
        for mod_id in self._LEARNING_MODULES:
            entry = module_map[mod_id]
            assert "initial_module_state" in entry, f"{mod_id} missing initial_module_state"
            ims = entry["initial_module_state"]
            assert "mastery" in ims, f"{mod_id}: missing mastery"
            assert "affect" in ims, f"{mod_id}: missing affect"
            assert "fluency" in ims, f"{mod_id}: missing fluency"

    def test_governance_modules_no_initial_module_state(self) -> None:
        cfg = _load_runtime_config()
        module_map = cfg["runtime"]["module_map"]
        for mod_id in self._GOVERNANCE_MODULES:
            entry = module_map[mod_id]
            assert "initial_module_state" not in entry, (
                f"{mod_id} should not have initial_module_state"
            )

    def test_freeform_module_has_initial_module_state(self) -> None:
        cfg = _load_runtime_config()
        entry = cfg["runtime"]["module_map"]["domain/edu/general-education/v1"]
        assert "initial_module_state" in entry
        ims = entry["initial_module_state"]
        assert "journaling_entry_count" in ims
        assert "vocabulary_tracking" in ims

    def test_mastery_dimensions_match_physics(self) -> None:
        """initial_module_state mastery keys should match the physics
        mastery_dimensions for each learning module."""
        import json

        cfg = _load_runtime_config()
        module_map = cfg["runtime"]["module_map"]
        for mod_id in self._LEARNING_MODULES:
            entry = module_map[mod_id]
            physics_path = _REPO_ROOT / entry["domain_physics_path"]
            physics = json.loads(physics_path.read_text(encoding="utf-8"))
            expected_dims = set(
                physics.get("module_state_schema", {}).get("mastery_dimensions", [])
            )
            actual_dims = set(entry["initial_module_state"]["mastery"].keys())
            assert actual_dims == expected_dims, (
                f"{mod_id}: mastery keys {actual_dims} != physics dims {expected_dims}"
            )


# ─────────────────────────────────────────────────────────────
# 3. Three-tier state priority — learning adapter
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestLearningAdapterThreeTier:
    """build_initial_learning_state uses 3-tier priority:
    DB module_state → initial_module_state → profile fallback."""

    def _build(self, **kwargs: Any) -> Any:
        import importlib.util
        import sys

        adapter_path = (
            _REPO_ROOT
            / "model-packs"
            / "education"
            / "controllers"
            / "learning_adapters.py"
        )
        mod_name = "test_learning_adapters_3tier"
        spec = importlib.util.spec_from_file_location(mod_name, str(adapter_path))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        if mod_name not in sys.modules:
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        else:
            mod = sys.modules[mod_name]
        return mod.build_initial_learning_state(**kwargs)

    def _profile_with_learning_state(self) -> dict[str, Any]:
        """Profile with legacy learning_state (backward compat)."""
        return {
            "learning_state": {
                "affect": {"salience": 0.3, "valence": -0.1, "arousal": 0.6},
                "mastery": {"equivalence_preserved": 0.1},
                "challenge_band": {"min_challenge": 0.2, "max_challenge": 0.6},
                "recent_window": {"window_turns": 5, "attempts": 2},
                "challenge": 0.25,
                "uncertainty": 0.9,
                "fluency": {"current_tier": "tier_1", "consecutive_correct": 1},
            }
        }

    def test_tier1_db_state_wins(self) -> None:
        """DB module_state takes priority over everything."""
        db_state = _sample_db_module_state()
        result = self._build(
            profile=self._profile_with_learning_state(),
            module_state=db_state,
            initial_module_state=_sample_initial_module_state(),
        )
        assert result.challenge == 0.45  # from db_state, not profile or init

    def test_tier2_initial_module_state_used_when_no_db(self) -> None:
        """When no DB state, initial_module_state from runtime-config is used."""
        init = _sample_initial_module_state()
        init["challenge"] = 0.35  # distinct from profile's 0.25
        result = self._build(
            profile=self._profile_with_learning_state(),
            module_state=None,
            initial_module_state=init,
        )
        assert result.challenge == 0.35

    def test_tier3_profile_fallback(self) -> None:
        """When neither DB nor runtime-config, fall back to profile."""
        result = self._build(
            profile=self._profile_with_learning_state(),
            module_state=None,
            initial_module_state=None,
        )
        assert result.challenge == 0.25  # from profile

    def test_empty_profile_with_initial_module_state(self) -> None:
        """New student with no profile learning_state uses initial_module_state."""
        result = self._build(
            profile={},
            module_state=None,
            initial_module_state=_sample_initial_module_state(),
        )
        assert result.challenge == 0.3  # from initial_module_state
        assert result.mastery["equivalence_preserved"] == 0.0


# ─────────────────────────────────────────────────────────────
# 4. Three-tier state priority — freeform adapter
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestFreeformAdapterThreeTier:
    """freeform_build_initial_state uses 3-tier priority."""

    def _build(self, profile: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        import importlib.util
        import sys

        adapter_path = (
            _REPO_ROOT
            / "model-packs"
            / "education"
            / "controllers"
            / "freeform_adapters.py"
        )
        mod_name = "test_freeform_adapters_3tier"
        spec = importlib.util.spec_from_file_location(mod_name, str(adapter_path))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        if mod_name not in sys.modules:
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        else:
            mod = sys.modules[mod_name]
        return mod.freeform_build_initial_state(profile, **kwargs)

    def test_tier1_db_state_wins(self) -> None:
        db_state = {"journaling_entry_count": 42, "last_reflection_utc": "2026-01-01T00:00:00Z"}
        result = self._build({}, module_state=db_state)
        assert result["journaling_entry_count"] == 42

    def test_tier2_initial_module_state(self) -> None:
        init = {"journaling_entry_count": 0, "last_reflection_utc": None}
        result = self._build({}, module_state=None, initial_module_state=init)
        assert result["journaling_entry_count"] == 0
        assert result["last_reflection_utc"] is None

    def test_tier3_profile_fallback(self) -> None:
        result = self._build({}, module_state=None, initial_module_state=None)
        assert result["journaling_entry_count"] == 0


# ─────────────────────────────────────────────────────────────
# 5. SVA Affect Baseline — EMA updates
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSVABaseline:
    """Verify the floating SVA baseline and per-module affect signatures."""

    def _serializer(self):
        import importlib.util
        import sys

        path = (
            _REPO_ROOT
            / "model-packs"
            / "education"
            / "controllers"
            / "education_profile_serializer.py"
        )
        mod_name = "test_edu_serializer_sva"
        spec = importlib.util.spec_from_file_location(mod_name, str(path))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        if mod_name not in sys.modules:
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        else:
            mod = sys.modules[mod_name]
        return mod

    def _make_profile_data(self) -> dict[str, Any]:
        return {
            "learning_state": {
                "affect_baseline": {
                    "salience": 0.5,
                    "valence": 0.0,
                    "arousal": 0.5,
                    "sample_count": 0,
                    "per_module": {},
                },
                "challenge": 0.3,
                "uncertainty": 0.8,
            }
        }

    def test_ema_first_update(self) -> None:
        """First affect reading shifts baseline by alpha."""
        mod = self._serializer()
        profile_data = self._make_profile_data()
        affect = {"salience": 0.8, "valence": 0.3, "arousal": 0.6}
        mod._update_affect_baseline(profile_data, "algebra-1", affect)
        ab = profile_data["learning_state"]["affect_baseline"]
        # EMA: 0.1 * 0.8 + 0.9 * 0.5 = 0.53
        assert ab["salience"] == pytest.approx(0.53, abs=1e-5)
        # EMA: 0.1 * 0.3 + 0.9 * 0.0 = 0.03
        assert ab["valence"] == pytest.approx(0.03, abs=1e-5)
        # EMA: 0.1 * 0.6 + 0.9 * 0.5 = 0.51
        assert ab["arousal"] == pytest.approx(0.51, abs=1e-5)
        assert ab["sample_count"] == 1

    def test_ema_multiple_updates_converge(self) -> None:
        """Repeated identical readings should converge baseline toward that reading."""
        mod = self._serializer()
        profile_data = self._make_profile_data()
        target = {"salience": 1.0, "valence": 1.0, "arousal": 1.0}
        for _ in range(100):
            mod._update_affect_baseline(profile_data, "test-mod", target)
        ab = profile_data["learning_state"]["affect_baseline"]
        assert ab["salience"] == pytest.approx(1.0, abs=0.01)
        assert ab["valence"] == pytest.approx(1.0, abs=0.01)
        assert ab["arousal"] == pytest.approx(1.0, abs=0.01)
        assert ab["sample_count"] == 100

    def test_per_module_signature_recorded(self) -> None:
        """Per-module affect snapshot includes delta_from_baseline."""
        mod = self._serializer()
        profile_data = self._make_profile_data()
        affect = {"salience": 0.9, "valence": -0.5, "arousal": 0.7}
        mod._update_affect_baseline(profile_data, "algebra-1", affect)
        sig = profile_data["learning_state"]["affect_baseline"]["per_module"]["algebra-1"]
        assert sig["salience"] == 0.9
        assert sig["valence"] == -0.5
        assert sig["arousal"] == 0.7
        assert "delta_from_baseline" in sig
        assert "updated_utc" in sig

    def test_per_module_delta_direction(self) -> None:
        """Delta should show how the module diverges from the baseline."""
        mod = self._serializer()
        profile_data = self._make_profile_data()
        # Baseline starts at S=0.5, V=0.0, A=0.5
        affect = {"salience": 0.5, "valence": -1.0, "arousal": 0.5}
        mod._update_affect_baseline(profile_data, "hard-module", affect)
        sig = profile_data["learning_state"]["affect_baseline"]["per_module"]["hard-module"]
        # Valence drops: current (-1.0) vs updated baseline (0.1*-1.0 + 0.9*0.0 = -0.1)
        assert sig["delta_from_baseline"]["valence"] < 0

    def test_no_affect_no_update(self) -> None:
        """When state has no affect, baseline should not be touched."""
        mod = self._serializer()
        profile_data = self._make_profile_data()
        # Simulate a dict-based orch_state with no affect
        result = mod.education_serialize_profile(
            orch_state={"turn_count": 5, "operator_id": "op1"},
            profile_data=profile_data,
            module_key="governance-mod",
        )
        ab = result["learning_state"]["affect_baseline"]
        assert ab["sample_count"] == 0  # unchanged

    def test_baseline_initialises_from_first_reading(self) -> None:
        """If affect_baseline is missing, first reading bootstraps it."""
        mod = self._serializer()
        profile_data = {"learning_state": {}}
        affect = {"salience": 0.6, "valence": 0.1, "arousal": 0.4}
        mod._update_affect_baseline(profile_data, "mod-1", affect)
        ab = profile_data["learning_state"]["affect_baseline"]
        assert ab["salience"] == 0.6
        assert ab["valence"] == 0.1
        assert ab["arousal"] == 0.4
        assert ab["sample_count"] == 1

    def test_multiple_modules_tracked(self) -> None:
        """Different modules should each have their own per_module signature."""
        mod = self._serializer()
        profile_data = self._make_profile_data()
        mod._update_affect_baseline(
            profile_data, "algebra-1", {"salience": 0.8, "valence": 0.2, "arousal": 0.6}
        )
        mod._update_affect_baseline(
            profile_data, "pre-algebra", {"salience": 0.4, "valence": -0.3, "arousal": 0.3}
        )
        per_mod = profile_data["learning_state"]["affect_baseline"]["per_module"]
        assert "algebra-1" in per_mod
        assert "pre-algebra" in per_mod
        assert per_mod["algebra-1"]["valence"] == 0.2
        assert per_mod["pre-algebra"]["valence"] == -0.3

    def test_serializer_does_not_overwrite_profile_learning_state(self) -> None:
        """The serializer should NOT replace profile learning_state with
        module-specific state — it only updates affect_baseline and
        persists module state to DB."""

        @dataclasses.dataclass
        class FakeAffect:
            salience: float = 0.7
            valence: float = 0.1
            arousal: float = 0.4

        @dataclasses.dataclass
        class FakeState:
            affect: FakeAffect = dataclasses.field(default_factory=FakeAffect)
            mastery: dict = dataclasses.field(default_factory=lambda: {"dim1": 0.5})
            challenge: float = 0.4

        mod = self._serializer()
        profile_data = self._make_profile_data()

        # Use a mock persistence that records calls
        saved = {}

        class MockPersistence:
            def save_module_state(self, uid, mk, state):
                saved["call"] = (uid, mk, state)

        result = mod.education_serialize_profile(
            orch_state=FakeState(),
            profile_data=profile_data,
            module_key="algebra-1",
            persistence=MockPersistence(),
            user_id="student-123",
        )
        # affect_baseline should be updated
        assert result["learning_state"]["affect_baseline"]["sample_count"] == 1
        # Domain-wide posture should NOT be overwritten by module state
        assert result["learning_state"]["challenge"] == 0.3  # original, not 0.4
        # Module state should be saved to DB
        assert "call" in saved
        assert saved["call"][0] == "student-123"
        assert saved["call"][1] == "algebra-1"
