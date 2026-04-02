"""Tests for the hierarchical profile template system (Base → Domain → Role).

Covers:
- Deep merge of profile layers
- Profile assembly from three YAML layers
- Role-aware profile creation (_ensure_user_profile)
- Backward compatibility when profile_templates is absent
- System-role → domain-role fallback mapping
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from lumina.api.config import (
    _assemble_profile,
    _deep_merge,
    _ensure_user_profile,
    _SYSTEM_ROLE_TO_DOMAIN_ROLE,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# _deep_merge tests
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}
        result = _deep_merge(base, overlay)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"prefs": {"lang": "en", "style": "step"}, "val": 1}
        overlay = {"prefs": {"style": "technical", "theme": "dark"}}
        result = _deep_merge(base, overlay)
        assert result == {"prefs": {"lang": "en", "style": "technical", "theme": "dark"}, "val": 1}

    def test_list_replacement(self):
        base = {"items": [1, 2, 3]}
        overlay = {"items": [4, 5]}
        result = _deep_merge(base, overlay)
        assert result == {"items": [4, 5]}

    def test_does_not_mutate_inputs(self):
        base = {"a": {"x": 1}}
        overlay = {"a": {"y": 2}}
        _ = _deep_merge(base, overlay)
        assert base == {"a": {"x": 1}}
        assert overlay == {"a": {"y": 2}}

    def test_empty_overlay(self):
        base = {"a": 1}
        assert _deep_merge(base, {}) == {"a": 1}

    def test_empty_base(self):
        overlay = {"b": 2}
        assert _deep_merge({}, overlay) == {"b": 2}


# ---------------------------------------------------------------------------
# _assemble_profile tests
# ---------------------------------------------------------------------------

class TestAssembleProfile:
    @pytest.fixture()
    def layer_dir(self, tmp_path):
        """Create temp YAML layer files."""
        base = tmp_path / "base.yaml"
        base.write_text(yaml.safe_dump({
            "entity_id": None,
            "domain_id": None,
            "preferences": {"language": "en"},
            "state": {},
        }), encoding="utf-8")

        domain_ext = tmp_path / "domain.yaml"
        domain_ext.write_text(yaml.safe_dump({
            "consent": {"magic_circle_accepted": False},
            "session_history": {"total_sessions": 0},
        }), encoding="utf-8")

        student_role = tmp_path / "student.yaml"
        student_role.write_text(yaml.safe_dump({
            "preferences": {"preferred_explanation_style": "step_by_step"},
            "learning_state": {"mastery": {"score": 0.0}, "challenge": 0.3},
        }), encoding="utf-8")

        teacher_role = tmp_path / "teacher.yaml"
        teacher_role.write_text(yaml.safe_dump({
            "preferences": {"explanation_style": "technical"},
            "educator_state": {"assigned_students": [], "escalation_preferences": {"receive_escalations": True}},
        }), encoding="utf-8")

        return {
            "base": str(base),
            "domain": str(domain_ext),
            "student": str(student_role),
            "teacher": str(teacher_role),
        }

    def test_full_student_assembly(self, layer_dir):
        profile = _assemble_profile(
            layer_dir["base"], layer_dir["domain"], layer_dir["student"],
        )
        # Base fields survive
        assert profile["entity_id"] is None
        assert profile["preferences"]["language"] == "en"
        # Domain fields added
        assert profile["consent"]["magic_circle_accepted"] is False
        assert profile["session_history"]["total_sessions"] == 0
        # Role fields added
        assert profile["learning_state"]["challenge"] == 0.3
        # Preference merge
        assert profile["preferences"]["preferred_explanation_style"] == "step_by_step"

    def test_full_teacher_assembly(self, layer_dir):
        profile = _assemble_profile(
            layer_dir["base"], layer_dir["domain"], layer_dir["teacher"],
        )
        assert profile["entity_id"] is None
        assert profile["consent"]["magic_circle_accepted"] is False
        assert profile["educator_state"]["assigned_students"] == []
        assert "learning_state" not in profile
        assert profile["preferences"]["explanation_style"] == "technical"

    def test_missing_layers_are_skipped(self, layer_dir):
        # Only base, no domain or role
        profile = _assemble_profile(layer_dir["base"], None, None)
        assert profile == {
            "entity_id": None,
            "domain_id": None,
            "preferences": {"language": "en"},
            "state": {},
        }

    def test_nonexistent_path_skipped(self, layer_dir):
        profile = _assemble_profile(
            layer_dir["base"], "/nonexistent/path.yaml", layer_dir["student"],
        )
        # Domain extension skipped, rest is base + role
        assert "consent" not in profile
        assert profile["learning_state"]["challenge"] == 0.3


# ---------------------------------------------------------------------------
# _ensure_user_profile — role-aware creation
# ---------------------------------------------------------------------------

class TestEnsureUserProfile:
    @pytest.fixture()
    def profile_env(self, tmp_path, monkeypatch):
        """Set up a temporary profiles directory and layer files."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        # Monkeypatch the _PROFILES_DIR used by config.py
        import lumina.api.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "_PROFILES_DIR", profiles_dir)

        layers = tmp_path / "layers"
        layers.mkdir()

        base = layers / "base.yaml"
        base.write_text(yaml.safe_dump({
            "entity_id": None, "domain_id": None, "preferences": {"language": "en"}, "state": {},
        }), encoding="utf-8")

        domain_ext = layers / "domain.yaml"
        domain_ext.write_text(yaml.safe_dump({
            "consent": {"magic_circle_accepted": False},
            "session_history": {"total_sessions": 0},
        }), encoding="utf-8")

        student = layers / "student.yaml"
        student.write_text(yaml.safe_dump({
            "learning_state": {"challenge": 0.3, "mastery": {"score": 0.0}},
        }), encoding="utf-8")

        teacher = layers / "teacher.yaml"
        teacher.write_text(yaml.safe_dump({
            "educator_state": {"assigned_students": []},
        }), encoding="utf-8")

        domain_authority = layers / "domain_authority.yaml"
        domain_authority.write_text(yaml.safe_dump({
            "educator_state": {"assigned_students": []},
            "management_state": {"domain_overview_enabled": True},
        }), encoding="utf-8")

        flat_template = layers / "flat.yaml"
        flat_template.write_text(yaml.safe_dump({
            "student_id": None, "domain_id": "domain/edu/algebra-level-1/v1",
            "learning_state": {"challenge": 0.3},
        }), encoding="utf-8")

        return {
            "profiles_dir": profiles_dir,
            "base": str(base),
            "domain": str(domain_ext),
            "student": str(student),
            "teacher": str(teacher),
            "domain_authority": str(domain_authority),
            "flat_template": str(flat_template),
        }

    def test_creates_student_profile_with_layers(self, profile_env):
        runtime = {
            "base_profile_path": profile_env["base"],
            "domain_profile_extension_path": profile_env["domain"],
            "profile_templates": {
                "default": profile_env["student"],
                "student": profile_env["student"],
                "teacher": profile_env["teacher"],
            },
        }
        path = _ensure_user_profile(
            "user_001", "education",
            template_path=profile_env["flat_template"],
            runtime=runtime, domain_role="student",
        )
        profile = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        assert profile["entity_id"] is None
        assert profile["consent"]["magic_circle_accepted"] is False
        assert profile["learning_state"]["challenge"] == 0.3
        assert "educator_state" not in profile

    def test_creates_teacher_profile_with_layers(self, profile_env):
        runtime = {
            "base_profile_path": profile_env["base"],
            "domain_profile_extension_path": profile_env["domain"],
            "profile_templates": {
                "default": profile_env["student"],
                "student": profile_env["student"],
                "teacher": profile_env["teacher"],
            },
        }
        path = _ensure_user_profile(
            "user_002", "education",
            template_path=profile_env["flat_template"],
            runtime=runtime, domain_role="teacher",
        )
        profile = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        assert profile["educator_state"]["assigned_students"] == []
        assert "learning_state" not in profile
        assert profile["consent"]["magic_circle_accepted"] is False

    def test_system_role_fallback_to_teacher(self, profile_env):
        runtime = {
            "base_profile_path": profile_env["base"],
            "domain_profile_extension_path": profile_env["domain"],
            "profile_templates": {
                "default": profile_env["student"],
                "student": profile_env["student"],
                "teacher": profile_env["teacher"],
                "domain_authority": profile_env["domain_authority"],
            },
        }
        path = _ensure_user_profile(
            "da_001", "education",
            template_path=profile_env["flat_template"],
            runtime=runtime, domain_role=None, system_role="domain_authority",
        )
        profile = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        # domain_authority maps to domain_authority profile
        assert "educator_state" in profile
        assert "management_state" in profile
        assert "learning_state" not in profile

    def test_backward_compat_flat_copy(self, profile_env):
        """Without profile_templates, falls back to shutil.copy2."""
        path = _ensure_user_profile(
            "user_flat", "education",
            template_path=profile_env["flat_template"],
        )
        profile = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        assert profile["domain_id"] == "domain/edu/algebra-level-1/v1"
        assert profile["learning_state"]["challenge"] == 0.3

    def test_existing_profile_not_overwritten(self, profile_env):
        """If profile already exists on disk, it should not be recreated."""
        runtime = {
            "base_profile_path": profile_env["base"],
            "domain_profile_extension_path": profile_env["domain"],
            "profile_templates": {
                "default": profile_env["student"],
                "student": profile_env["student"],
                "teacher": profile_env["teacher"],
            },
        }
        # First call creates profile as student
        path1 = _ensure_user_profile(
            "user_existing", "education",
            template_path=profile_env["flat_template"],
            runtime=runtime, domain_role="student",
        )
        # Second call with teacher role should NOT overwrite
        path2 = _ensure_user_profile(
            "user_existing", "education",
            template_path=profile_env["flat_template"],
            runtime=runtime, domain_role="teacher",
        )
        assert path1 == path2
        profile = yaml.safe_load(Path(path2).read_text(encoding="utf-8"))
        # Still has student fields from first creation
        assert "learning_state" in profile

    def test_default_role_when_unknown(self, profile_env):
        """Unknown domain_role falls back to 'default' template."""
        runtime = {
            "base_profile_path": profile_env["base"],
            "domain_profile_extension_path": profile_env["domain"],
            "profile_templates": {
                "default": profile_env["student"],
                "student": profile_env["student"],
                "teacher": profile_env["teacher"],
            },
        }
        path = _ensure_user_profile(
            "user_unknown", "education",
            template_path=profile_env["flat_template"],
            runtime=runtime, domain_role="observer",
        )
        profile = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        # Falls back to default (student)
        assert "learning_state" in profile


# ---------------------------------------------------------------------------
# Integration: real domain-pack layer files
# ---------------------------------------------------------------------------

class TestRealLayerFiles:
    """Verify the actual YAML files in domain-packs/ compose correctly."""

    BASE_PATH = REPO_ROOT / "domain-packs" / "system" / "cfg" / "base-entity-profile.yaml"
    DOMAIN_EXT = REPO_ROOT / "domain-packs" / "education" / "cfg" / "domain-profile-extension.yaml"
    PROFILES_DIR = REPO_ROOT / "domain-packs" / "education" / "profiles"

    @pytest.mark.parametrize("role,expected_key,absent_key", [
        ("student", "learning_state", "educator_state"),
        ("teacher", "educator_state", "learning_state"),
        ("teaching_assistant", "assistant_state", "educator_state"),
        ("parent", "guardian_state", "learning_state"),
    ])
    def test_layer_composition(self, role, expected_key, absent_key):
        role_path = self.PROFILES_DIR / f"{role}.yaml"
        assert role_path.exists(), f"Missing role template: {role_path}"

        profile = _assemble_profile(
            str(self.BASE_PATH), str(self.DOMAIN_EXT), str(role_path),
        )
        # Base fields
        assert "entity_id" in profile
        assert "preferences" in profile
        assert profile["preferences"]["language"] == "en"
        # Domain extension fields
        assert "consent" in profile
        assert "session_history" in profile
        # Role-specific fields
        assert expected_key in profile, f"Expected '{expected_key}' in {role} profile"
        assert absent_key not in profile, f"Unexpected '{absent_key}' in {role} profile"


# ---------------------------------------------------------------------------
# System-role mapping table coverage
# ---------------------------------------------------------------------------

class TestSystemRoleMapping:
    def test_all_system_roles_mapped(self):
        expected_roles = {"root", "domain_authority", "it_support", "qa", "auditor", "user"}
        assert set(_SYSTEM_ROLE_TO_DOMAIN_ROLE.keys()) == expected_roles

    def test_authority_roles_map_to_domain_authority(self):
        for role in ("root", "domain_authority"):
            assert _SYSTEM_ROLE_TO_DOMAIN_ROLE[role] == "domain_authority"

    def test_support_roles_map_to_teacher(self):
        assert _SYSTEM_ROLE_TO_DOMAIN_ROLE["it_support"] == "teacher"

    def test_regular_roles_map_to_student(self):
        for role in ("qa", "auditor", "user"):
            assert _SYSTEM_ROLE_TO_DOMAIN_ROLE[role] == "student"
