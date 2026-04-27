"""Structural consistency tests for standardized domain pack layout."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_PACKS = REPO_ROOT / "model-packs"
SYSTEM_PACK = DOMAIN_PACKS / "system"
EDUCATION_PACK = DOMAIN_PACKS / "education"
AGRICULTURE_PACK = DOMAIN_PACKS / "agriculture"
ASSISTANT_PACK = DOMAIN_PACKS / "assistant"

ALL_PACKS = [SYSTEM_PACK, EDUCATION_PACK, AGRICULTURE_PACK, ASSISTANT_PACK]
PACK_IDS = ["system", "education", "agriculture", "assistant"]


class TestReferenceDirectoryExists:
    @pytest.mark.parametrize("pack", ALL_PACKS, ids=PACK_IDS)
    def test_reference_dir(self, pack: Path):
        assert (pack / "domain-lib" / "reference").is_dir()


class TestTurnInterpretationSpecExists:
    @pytest.mark.parametrize("pack", ALL_PACKS, ids=PACK_IDS)
    def test_turn_interpretation_spec(self, pack: Path):
        spec = pack / "domain-lib" / "reference" / "turn-interpretation-spec-v1.md"
        assert spec.is_file(), f"Missing turn-interpretation-spec-v1.md in {pack.name}"


class TestSystemCommandInterpreterSpec:
    def test_command_interpreter_spec_exists(self):
        spec = SYSTEM_PACK / "domain-lib" / "reference" / "command-interpreter-spec-v1.md"
        assert spec.is_file()


class TestSensorsDirectory:
    def test_system_sensors(self):
        assert (SYSTEM_PACK / "domain-lib" / "sensors").is_dir()

    def test_agriculture_sensors(self):
        assert (AGRICULTURE_PACK / "domain-lib" / "sensors").is_dir()


class TestEducationSpecsInReference:
    """Education spec .md files must be in reference/, not domain-lib root."""

    EXPECTED_SPECS = [
        "compressed-state-estimators.md",
        "zpd-monitor-spec-v1.md",
        "fatigue-estimation-spec-v1.md",
    ]

    @pytest.mark.parametrize("spec_name", EXPECTED_SPECS)
    def test_spec_in_reference(self, spec_name: str):
        ref = EDUCATION_PACK / "domain-lib" / "reference" / spec_name
        assert ref.is_file(), f"{spec_name} should be in domain-lib/reference/"

    @pytest.mark.parametrize("spec_name", EXPECTED_SPECS)
    def test_spec_not_at_root(self, spec_name: str):
        root = EDUCATION_PACK / "domain-lib" / spec_name
        assert not root.exists(), f"{spec_name} should NOT be at domain-lib root"


class TestPromptsContainOnlyPersona:
    """prompts/ should contain only persona files, no interpretation specs."""

    @pytest.mark.parametrize("pack", ALL_PACKS, ids=PACK_IDS)
    def test_no_turn_interpretation_in_prompts(self, pack: Path):
        prompts = pack / "prompts"
        if prompts.is_dir():
            assert not (prompts / "turn-interpretation.md").exists()

    @pytest.mark.parametrize("pack", ALL_PACKS, ids=PACK_IDS)
    def test_no_command_translator_in_prompts(self, pack: Path):
        prompts = pack / "prompts"
        if prompts.is_dir():
            assert not (prompts / "command-translator.md").exists()

    @pytest.mark.parametrize("pack", ALL_PACKS, ids=PACK_IDS)
    def test_persona_file_exists(self, pack: Path):
        persona = pack / "prompts" / "domain-persona-v1.md"
        assert persona.is_file(), f"Missing domain-persona-v1.md in {pack.name}"

    @pytest.mark.parametrize("pack", ALL_PACKS, ids=PACK_IDS)
    def test_no_old_persona_file(self, pack: Path):
        old = pack / "prompts" / "domain-system-override.md"
        assert not old.exists(), f"Old file domain-system-override.md still in {pack.name}"
