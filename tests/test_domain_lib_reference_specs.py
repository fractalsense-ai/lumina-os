"""Content validation for domain-lib reference spec files."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_PACKS = REPO_ROOT / "model-packs"

ALL_TURN_SPECS = [
    DOMAIN_PACKS / "system" / "domain-lib" / "reference" / "turn-interpretation-spec-v1.md",
    DOMAIN_PACKS / "education" / "domain-lib" / "reference" / "turn-interpretation-spec-v1.md",
    DOMAIN_PACKS / "agriculture" / "domain-lib" / "reference" / "turn-interpretation-spec-v1.md",
]
SPEC_IDS = ["system", "education", "agriculture"]

COMMAND_SPEC = (
    DOMAIN_PACKS / "system" / "domain-lib" / "reference" / "command-interpreter-spec-v1.md"
)


class TestTurnInterpretationSpecContent:
    @pytest.mark.parametrize("spec_path", ALL_TURN_SPECS, ids=SPEC_IDS)
    def test_has_version_header(self, spec_path: Path):
        text = spec_path.read_text(encoding="utf-8")
        assert "version:" in text.lower()

    @pytest.mark.parametrize("spec_path", ALL_TURN_SPECS, ids=SPEC_IDS)
    def test_contains_json_schema_hint(self, spec_path: Path):
        """Each turn interpretation spec should describe a JSON output schema."""
        text = spec_path.read_text(encoding="utf-8")
        assert "json" in text.lower(), "Spec should reference JSON output format"


class TestCommandInterpreterSpecContent:
    def test_has_version_header(self):
        text = COMMAND_SPEC.read_text(encoding="utf-8")
        assert "version:" in text.lower()

    def test_contains_disambiguation_rules(self):
        text = COMMAND_SPEC.read_text(encoding="utf-8")
        assert "disambiguat" in text.lower(), "Spec should contain disambiguation rules"

    def test_contains_param_schemas(self):
        text = COMMAND_SPEC.read_text(encoding="utf-8")
        assert "param" in text.lower(), "Spec should contain parameter schemas"


class TestAllSpecsHaveVersionHeaders:
    """Every .md file in any domain-lib/reference/ should have a version header."""

    @staticmethod
    def _collect_reference_specs() -> list[Path]:
        specs = []
        for pack_dir in DOMAIN_PACKS.iterdir():
            if not pack_dir.is_dir():
                continue
            ref_dir = pack_dir / "domain-lib" / "reference"
            if ref_dir.is_dir():
                specs.extend(ref_dir.glob("*.md"))
        return specs

    def test_at_least_one_spec_found(self):
        specs = self._collect_reference_specs()
        assert len(specs) >= 3, "Expected at least 3 reference specs across all packs"

    def test_each_spec_has_version(self):
        for spec_path in self._collect_reference_specs():
            text = spec_path.read_text(encoding="utf-8")
            assert "version:" in text.lower(), (
                f"{spec_path.relative_to(REPO_ROOT)} missing version header"
            )
