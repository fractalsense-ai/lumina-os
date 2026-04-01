"""Tests for module-map routing and the education module-level evidence schemas.

Covers:
  1. runtime-config.yaml has a module_map section with exactly 4 entries
  2. Each module_map entry's domain_physics_path resolves to a valid, loadable JSON file
  3. All three new evidence-schema.json files exist and are valid JSON with correct schema_id/domain_id
  4. Module-selection logic: given a student profile declaring domain_id X, the
     correct domain_physics_path is returned (overrides the static default)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EDU_CFG = REPO_ROOT / "domain-packs" / "education" / "cfg" / "runtime-config.yaml"
EDU_MODULES = REPO_ROOT / "domain-packs" / "education" / "modules"

_EXPECTED_MODULE_IDS = [
    "domain/edu/pre-algebra/v1",
    "domain/edu/algebra-intro/v1",
    "domain/edu/algebra-1/v1",
]

# All module_map entries (includes the legacy module and default staging module)
_ALL_MODULE_MAP_IDS = _EXPECTED_MODULE_IDS + [
    "domain/edu/algebra-level-1/v1",
    "domain/edu/general-education/v1",
]

_EXPECTED_SCHEMA_IDS = {
    "domain/edu/pre-algebra/v1":    "lumina:evidence:education:pre-algebra:v1",
    "domain/edu/algebra-intro/v1":  "lumina:evidence:education:algebra-intro:v1",
    "domain/edu/algebra-1/v1":      "lumina:evidence:education:algebra-1:v1",
}

_MODULE_DIR_MAP = {
    "domain/edu/pre-algebra/v1":    "pre-algebra",
    "domain/edu/algebra-intro/v1":  "algebra-intro",
    "domain/edu/algebra-1/v1":      "algebra-1",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runtime_cfg() -> dict:
    with open(EDU_CFG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["runtime"]


@pytest.fixture(scope="module")
def module_map(runtime_cfg) -> dict:
    return runtime_cfg.get("module_map", {})


# ---------------------------------------------------------------------------
# Module-map structure
# ---------------------------------------------------------------------------

class TestModuleMapStructure:
    def test_module_map_key_exists(self, runtime_cfg):
        assert "module_map" in runtime_cfg, (
            "runtime-config.yaml missing 'module_map' under runtime:"
        )

    def test_module_map_has_five_entries(self, module_map):
        assert len(module_map) == 5, (
            f"Expected 5 module_map entries, got {len(module_map)}: {list(module_map.keys())}"
        )

    @pytest.mark.parametrize("domain_id", _ALL_MODULE_MAP_IDS)
    def test_expected_domain_ids_present(self, module_map, domain_id):
        assert domain_id in module_map, f"module_map missing entry for {domain_id!r}"

    @pytest.mark.parametrize("domain_id", _ALL_MODULE_MAP_IDS)
    def test_each_entry_has_domain_physics_path(self, module_map, domain_id):
        entry = module_map[domain_id]
        assert "domain_physics_path" in entry, (
            f"module_map[{domain_id!r}] missing 'domain_physics_path'"
        )
        assert isinstance(entry["domain_physics_path"], str)
        assert entry["domain_physics_path"].strip()


# ---------------------------------------------------------------------------
# Domain-physics files referenced by module_map exist and parse
# ---------------------------------------------------------------------------

class TestModuleMapPhysicsPaths:
    @pytest.mark.parametrize("domain_id", _ALL_MODULE_MAP_IDS)
    def test_domain_physics_path_file_exists(self, module_map, domain_id):
        path_str = module_map[domain_id]["domain_physics_path"]
        path = REPO_ROOT / path_str
        assert path.exists(), f"{path_str} does not exist (referenced by module_map[{domain_id!r}])"

    @pytest.mark.parametrize("domain_id", _ALL_MODULE_MAP_IDS)
    def test_domain_physics_json_is_valid(self, module_map, domain_id):
        path_str = module_map[domain_id]["domain_physics_path"]
        path = REPO_ROOT / path_str
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), f"{path_str} did not load as a JSON object"
        # Domain-physics files use 'id' (not 'domain_id') as the domain identifier
        assert "id" in data or "domain_id" in data, (
            f"{path_str} missing 'id' or 'domain_id' key"
        )


# ---------------------------------------------------------------------------
# Evidence schema files
# ---------------------------------------------------------------------------

class TestEvidenceSchemaFiles:
    @pytest.mark.parametrize("domain_id", _EXPECTED_MODULE_IDS)
    def test_evidence_schema_file_exists(self, domain_id):
        module_dir = _MODULE_DIR_MAP[domain_id]
        schema_path = EDU_MODULES / module_dir / "evidence-schema.json"
        assert schema_path.exists(), (
            f"evidence-schema.json missing in modules/{module_dir}/"
        )

    @pytest.mark.parametrize("domain_id", _EXPECTED_MODULE_IDS)
    def test_evidence_schema_is_valid_json(self, domain_id):
        module_dir = _MODULE_DIR_MAP[domain_id]
        schema_path = EDU_MODULES / module_dir / "evidence-schema.json"
        with open(schema_path, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    @pytest.mark.parametrize("domain_id", _EXPECTED_MODULE_IDS)
    def test_evidence_schema_has_correct_schema_id(self, domain_id):
        module_dir = _MODULE_DIR_MAP[domain_id]
        schema_path = EDU_MODULES / module_dir / "evidence-schema.json"
        with open(schema_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("schema_id") == _EXPECTED_SCHEMA_IDS[domain_id], (
            f"schema_id mismatch in {module_dir}/evidence-schema.json: "
            f"got {data.get('schema_id')!r}, expected {_EXPECTED_SCHEMA_IDS[domain_id]!r}"
        )

    @pytest.mark.parametrize("domain_id", _EXPECTED_MODULE_IDS)
    def test_evidence_schema_has_correct_domain_id(self, domain_id):
        module_dir = _MODULE_DIR_MAP[domain_id]
        schema_path = EDU_MODULES / module_dir / "evidence-schema.json"
        with open(schema_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("domain_id") == domain_id

    @pytest.mark.parametrize("domain_id", _EXPECTED_MODULE_IDS)
    def test_evidence_schema_has_fields(self, domain_id):
        module_dir = _MODULE_DIR_MAP[domain_id]
        schema_path = EDU_MODULES / module_dir / "evidence-schema.json"
        with open(schema_path, encoding="utf-8") as f:
            data = json.load(f)
        fields = data.get("fields", {})
        assert len(fields) >= 10, (
            f"{module_dir}/evidence-schema.json has only {len(fields)} fields; expected ≥10"
        )

    def test_pre_algebra_has_law2_fields(self):
        schema_path = EDU_MODULES / "pre-algebra" / "evidence-schema.json"
        with open(schema_path, encoding="utf-8") as f:
            data = json.load(f)
        fields = data["fields"]
        assert "reversibility_order_correct" in fields
        assert "inequality_direction_correct" in fields

    def test_algebra_intro_has_law3_and_law5_fields(self):
        schema_path = EDU_MODULES / "algebra-intro" / "evidence-schema.json"
        with open(schema_path, encoding="utf-8") as f:
            data = json.load(f)
        fields = data["fields"]
        assert "substitution_valid" in fields
        assert "relationship_correctly_mapped" in fields
        # Also inherits Law 2 fields
        assert "reversibility_order_correct" in fields

    def test_algebra_1_has_all_six_law_fields(self):
        schema_path = EDU_MODULES / "algebra-1" / "evidence-schema.json"
        with open(schema_path, encoding="utf-8") as f:
            data = json.load(f)
        fields = data["fields"]
        for expected_field in [
            "equivalence_preserved",          # Law 1
            "reversibility_order_correct",     # Law 2
            "inequality_direction_correct",    # Law 2B
            "substitution_valid",              # Law 3
            "structure_preserved",             # Law 4
            "relationship_correctly_mapped",   # Law 5
            "model_accurately_transcribed",    # Law 6
        ]:
            assert expected_field in fields, (
                f"algebra-1/evidence-schema.json missing field: {expected_field!r}"
            )


# ---------------------------------------------------------------------------
# Module routing logic
# ---------------------------------------------------------------------------

class TestModuleRoutingLogic:
    """Verify the module-selection logic: module_map lookup overrides static default."""

    def _resolve_domain_physics_path(
        self, runtime: dict, profile: dict
    ) -> str:
        """Replicate the routing logic from _build_domain_context in server.py."""
        default_path = runtime["domain_physics_path"]
        module_map = runtime.get("module_map") or {}
        domain_id = profile.get("domain_id") or profile.get("subject_domain_id")
        if domain_id and domain_id in module_map:
            return module_map[domain_id]["domain_physics_path"]
        return default_path

    def test_no_domain_id_uses_static_default(self, runtime_cfg):
        profile = {}
        result = self._resolve_domain_physics_path(runtime_cfg, profile)
        assert result == runtime_cfg["domain_physics_path"]

    def test_unknown_domain_id_uses_static_default(self, runtime_cfg):
        profile = {"domain_id": "domain/edu/unknown/v1"}
        result = self._resolve_domain_physics_path(runtime_cfg, profile)
        assert result == runtime_cfg["domain_physics_path"]

    @pytest.mark.parametrize("domain_id", _ALL_MODULE_MAP_IDS)
    def test_known_domain_id_routes_to_module_path(self, runtime_cfg, module_map, domain_id):
        profile = {"domain_id": domain_id}
        result = self._resolve_domain_physics_path(runtime_cfg, profile)
        expected = module_map[domain_id]["domain_physics_path"]
        assert result == expected, (
            f"Routing failed for {domain_id!r}: got {result!r}, expected {expected!r}"
        )

    def test_algebra_1_routes_to_algebra_1_physics(self, runtime_cfg):
        profile = {"domain_id": "domain/edu/algebra-1/v1"}
        result = self._resolve_domain_physics_path(runtime_cfg, profile)
        assert "algebra-1" in result

    def test_pre_algebra_routes_to_pre_algebra_physics(self, runtime_cfg):
        profile = {"domain_id": "domain/edu/pre-algebra/v1"}
        result = self._resolve_domain_physics_path(runtime_cfg, profile)
        assert "pre-algebra" in result

    def test_subject_domain_id_fallback_key(self, runtime_cfg):
        # Support alternative key name used in some profile templates
        profile = {"subject_domain_id": "domain/edu/algebra-intro/v1"}
        result = self._resolve_domain_physics_path(runtime_cfg, profile)
        assert "algebra-intro" in result
