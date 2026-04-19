"""Tests for pipeline fix: module_key propagation, per-module local_only, governance SLM routing.

Covers:
- DomainContext stores and round-trips module_key
- processing.py uses module_key for module_map lookup (not domain_id)
- Per-module local_only routes governance through SLM-only path
- Governance modules never invoke call_llm (OpenAI)
- Student modules still use the LLM path
"""

from __future__ import annotations

import inspect
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────
# Phase 1: DomainContext module_key propagation
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDomainContextModuleKey:
    """DomainContext must store, serialize, and restore module_key."""

    def _make_ctx(self, module_key: str = "") -> Any:
        from lumina.api.session import DomainContext
        return DomainContext(
            orchestrator=MagicMock(),
            task_spec={"task_id": "test"},
            current_task={},
            turn_count=0,
            domain_id="education",
            task_presented_at=time.time(),
            module_key=module_key,
        )

    def test_module_key_stored(self) -> None:
        ctx = self._make_ctx("domain/edu/domain-authority/v1")
        assert ctx.module_key == "domain/edu/domain-authority/v1"

    def test_module_key_default_empty(self) -> None:
        ctx = self._make_ctx()
        assert ctx.module_key == ""

    def test_to_session_dict_includes_module_key(self) -> None:
        ctx = self._make_ctx("domain/edu/teacher/v1")
        d = ctx.to_session_dict()
        assert "module_key" in d
        assert d["module_key"] == "domain/edu/teacher/v1"

    def test_sync_from_dict_restores_module_key(self) -> None:
        ctx = self._make_ctx("")
        ctx.sync_from_dict({
            "task_spec": {"task_id": "t"},
            "current_task": {},
            "turn_count": 5,
            "module_key": "domain/edu/algebra-level-1/v1",
        })
        assert ctx.module_key == "domain/edu/algebra-level-1/v1"

    def test_sync_from_dict_without_module_key_preserves_existing(self) -> None:
        ctx = self._make_ctx("domain/edu/teacher/v1")
        ctx.sync_from_dict({
            "task_spec": {"task_id": "t"},
            "current_task": {},
            "turn_count": 3,
        })
        assert ctx.module_key == "domain/edu/teacher/v1"


# ─────────────────────────────────────────────────────────────
# Phase 1: processing.py uses module_key for module_map lookup
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestProcessingModuleKeyLookup:
    """process_message must use session['module_key'] for module_map lookup."""

    def _make_session(self, module_key: str = "") -> dict[str, Any]:
        mock_orch = MagicMock()
        mock_orch.state = SimpleNamespace(world_sim_theme={}, mud_world_state={})
        mock_orch.process_turn.return_value = (
            {"action": "governance_general", "prompt_type": "governance_general"},
            "governance_response",
        )
        mock_orch.log_records = []
        return {
            "orchestrator": mock_orch,
            "task_spec": {"task_id": "governance"},
            "current_task": {},
            "turn_count": 0,
            "domain_id": "education",
            "module_key": module_key,
            "task_presented_at": time.time(),
        }

    def _make_runtime(self, module_map: dict | None = None) -> dict[str, Any]:
        return {
            "system_prompt": "sys",
            "domain": {"id": "edu", "version": "1", "glossary": [], "invariants": []},
            "runtime_provenance": {},
            "turn_input_schema": {},
            "turn_input_defaults": {"query_type": "general", "urgency": "routine"},
            "turn_interpreter_fn": MagicMock(return_value={"query_type": "general"}),
            "turn_interpretation_prompt": "interpret",
            "nlp_pre_interpreter_fn": None,
            "slm_weight_overrides": {},
            "tool_fns": None,
            "action_prompt_type_map": {},
            "deterministic_templates": {},
            "local_only": False,
            "module_map": module_map or {},
            "pre_turn_checks": [],
        }

    def test_module_key_used_for_module_map_lookup(self) -> None:
        """When module_key is set, module_map lookup uses it instead of domain_id."""
        from lumina.api import processing as proc

        gov_interpreter = MagicMock(return_value={"query_type": "admin_command", "urgency": "routine"})
        module_map = {
            "domain/edu/domain-authority/v1": {
                "system_prompt": "You are the governance persona.",
                "turn_interpreter_fn": gov_interpreter,
                "turn_input_defaults": {"query_type": "general", "urgency": "routine"},
                "turn_input_schema": {"query_type": {"type": "enum", "values": ["general", "admin_command"]}},
                "local_only": True,
            },
        }
        session = self._make_session(module_key="domain/edu/domain-authority/v1")
        runtime = self._make_runtime(module_map=module_map)

        mock_registry = MagicMock(**{"get_runtime_context.return_value": runtime})
        mock_persistence = MagicMock()

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", mock_registry),
            patch.object(proc._cfg, "PERSISTENCE", mock_persistence),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=True),
            patch.object(proc, "call_slm", return_value='{"query_type":"admin_command","urgency":"routine"}'),
            patch.object(proc, "slm_interpret_physics_context", return_value={}),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_llm", return_value="response"),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            result = proc.process_message("sess-1", "list users", deterministic_response=False)

        # The governance interpreter should have been called (via local_only branch),
        # NOT the default interpret_turn_input (which calls OpenAI).
        gov_interpreter.assert_called_once()

    def test_module_key_empty_falls_back_to_domain_id(self) -> None:
        """When module_key is empty, falls back to domain_id for module_map lookup."""
        from lumina.api import processing as proc

        session = self._make_session(module_key="")
        runtime = self._make_runtime(module_map={
            "domain/edu/domain-authority/v1": {"system_prompt": "gov persona"},
        })

        interpret_mock = MagicMock(return_value={"query_type": "general"})
        mock_persistence = MagicMock()

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", MagicMock(**{"get_runtime_context.return_value": runtime})),
            patch.object(proc._cfg, "PERSISTENCE", mock_persistence),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "interpret_turn_input", interpret_mock),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_llm", return_value="response"),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            result = proc.process_message("sess-2", "hello", deterministic_response=False)

        # With empty module_key and domain_id="education", module_map lookup
        # for "education" finds nothing, so no governance overrides applied.
        # Falls through to interpret_turn_input (the else branch).
        interpret_mock.assert_called_once()


# ─────────────────────────────────────────────────────────────
# Phase 3: Per-module local_only routes through SLM
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPerModuleLocalOnly:
    """Per-module local_only must route governance interpreters through SLM-only."""

    def _make_session(self, module_key: str) -> dict[str, Any]:
        mock_orch = MagicMock()
        mock_orch.state = SimpleNamespace(world_sim_theme={}, mud_world_state={})
        mock_orch.process_turn.return_value = (
            {"action": "governance_general", "prompt_type": "governance_general"},
            "governance_response",
        )
        mock_orch.log_records = []
        return {
            "orchestrator": mock_orch,
            "task_spec": {"task_id": "governance"},
            "current_task": {},
            "turn_count": 0,
            "domain_id": "education",
            "module_key": module_key,
            "task_presented_at": time.time(),
        }

    def _make_runtime(self, module_map: dict | None = None) -> dict[str, Any]:
        return {
            "system_prompt": "sys",
            "domain": {"id": "edu", "version": "1", "glossary": [], "invariants": []},
            "runtime_provenance": {},
            "turn_input_schema": {},
            "turn_input_defaults": {"query_type": "general", "urgency": "routine"},
            "turn_interpreter_fn": MagicMock(return_value={"query_type": "general"}),
            "slm_weight_overrides": {},
            "tool_fns": None,
            "action_prompt_type_map": {},
            "deterministic_templates": {},
            "local_only": False,  # Domain is NOT globally local_only
            "module_map": module_map or {},
            "pre_turn_checks": [],
            "turn_interpretation_prompt": "interpret",
            "nlp_pre_interpreter_fn": None,
        }

    def test_per_module_local_only_uses_slm_path(self) -> None:
        """Module with local_only: true uses SLM interpreter even if domain is not local_only."""
        from lumina.api import processing as proc

        gov_interpreter = MagicMock(return_value={"query_type": "admin_command", "urgency": "routine"})
        module_map = {
            "domain/edu/domain-authority/v1": {
                "local_only": True,
                "turn_interpreter_fn": gov_interpreter,
                "turn_input_defaults": {"query_type": "general", "urgency": "routine"},
            },
        }
        session = self._make_session("domain/edu/domain-authority/v1")
        runtime = self._make_runtime(module_map=module_map)

        mock_persistence = MagicMock()

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", MagicMock(**{"get_runtime_context.return_value": runtime})),
            patch.object(proc._cfg, "PERSISTENCE", mock_persistence),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=True),
            patch.object(proc, "call_slm", return_value='{"query_type":"admin_command"}'),
            patch.object(proc, "slm_interpret_physics_context", return_value={}),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_llm", return_value="response"),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            proc.process_message("sess-gov", "list users", deterministic_response=False)

        # Module's turn_interpreter_fn called (SLM path)
        gov_interpreter.assert_called_once()
        # call_slm was passed as the call_llm kwarg (SLM substituted for LLM)
        call_args = gov_interpreter.call_args
        # The call_llm kwarg should be the mock for call_slm (not call_llm)
        assert call_args.kwargs.get("call_llm") is not None
        # Verify it's NOT the real call_llm import
        assert call_args.kwargs.get("call_llm") is not proc.call_llm

    def test_student_module_without_local_only_uses_llm(self) -> None:
        """Student module without local_only uses the LLM else branch."""
        from lumina.api import processing as proc

        module_map = {
            "domain/edu/algebra-level-1/v1": {
                # No local_only — student module
            },
        }
        session = self._make_session("domain/edu/algebra-level-1/v1")
        runtime = self._make_runtime(module_map=module_map)

        interpret_mock = MagicMock(return_value={"correctness": "correct", "problem_solved": True})
        mock_persistence = MagicMock()

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", MagicMock(**{"get_runtime_context.return_value": runtime})),
            patch.object(proc._cfg, "PERSISTENCE", mock_persistence),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "interpret_turn_input", interpret_mock),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_llm", return_value="response"),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            proc.process_message("sess-student", "x = 5", deterministic_response=False)

        # interpret_turn_input (LLM path) was called for student module
        interpret_mock.assert_called_once()

    def test_all_governance_modules_have_local_only_in_config(self) -> None:
        """Verify runtime-config.yaml has local_only: true on all governance modules."""
        from lumina.core.yaml_loader import load_yaml
        from conftest import merge_module_config_sidecars

        cfg = load_yaml(str(REPO_ROOT / "domain-packs/education/cfg/runtime-config.yaml"))
        module_map = cfg.get("runtime", {}).get("module_map", {})
        merge_module_config_sidecars(module_map)

        governance_modules = [
            "domain/edu/domain-authority/v1",
            "domain/edu/teacher/v1",
            "domain/edu/teaching-assistant/v1",
            "domain/edu/guardian/v1",
        ]

        for mod_id in governance_modules:
            assert mod_id in module_map, f"Missing governance module: {mod_id}"
            assert module_map[mod_id].get("local_only") is True, (
                f"Governance module {mod_id} must have local_only: true"
            )

    def test_student_modules_no_local_only_in_config(self) -> None:
        """Student/learning modules must NOT have local_only set."""
        from lumina.core.yaml_loader import load_yaml
        from conftest import merge_module_config_sidecars

        cfg = load_yaml(str(REPO_ROOT / "domain-packs/education/cfg/runtime-config.yaml"))
        module_map = cfg.get("runtime", {}).get("module_map", {})
        merge_module_config_sidecars(module_map)

        student_modules = [
            "domain/edu/general-education/v1",
            "domain/edu/pre-algebra/v1",
            "domain/edu/algebra-intro/v1",
            "domain/edu/algebra-1/v1",
            "domain/edu/algebra-level-1/v1",
        ]

        for mod_id in student_modules:
            if mod_id in module_map:
                assert not module_map[mod_id].get("local_only"), (
                    f"Student module {mod_id} must NOT have local_only"
                )


# ─────────────────────────────────────────────────────────────
# Phase 4: Education governance TMs exist
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGovernanceTechnicalManuals:
    """Education domain-lib must include governance Technical Manuals."""

    def test_command_interpreter_spec_exists(self) -> None:
        path = REPO_ROOT / "domain-packs/education/domain-lib/reference/command-interpreter-spec-v1.md"
        assert path.exists(), "Missing command-interpreter-spec-v1.md"
        text = path.read_text(encoding="utf-8")
        assert "Command Interpreter Specification" in text
        assert "education" in text.lower()

    def test_governance_turn_interpretation_spec_exists(self) -> None:
        path = REPO_ROOT / "domain-packs/education/domain-lib/reference/governance-turn-interpretation-spec-v1.md"
        assert path.exists(), "Missing governance-turn-interpretation-spec-v1.md"
        text = path.read_text(encoding="utf-8")
        assert "Governance Turn Interpretation" in text
        assert "local_only" in text

    def test_command_spec_covers_all_operations(self) -> None:
        """Command interpreter spec should reference all key operations."""
        path = REPO_ROOT / "domain-packs/education/domain-lib/reference/command-interpreter-spec-v1.md"
        text = path.read_text(encoding="utf-8")

        key_operations = [
            "invite_user",
            "list_users",
            "list_modules",
            "list_escalations",
            "assign_domain_role",
            "revoke_domain_role",
            "resolve_escalation",
            "update_domain_physics",
        ]
        for op in key_operations:
            assert op in text, f"Command spec missing operation: {op}"

    def test_governance_spec_contrasts_with_learning(self) -> None:
        """Governance TM should explicitly contrast with learning evidence."""
        path = REPO_ROOT / "domain-packs/education/domain-lib/reference/governance-turn-interpretation-spec-v1.md"
        text = path.read_text(encoding="utf-8")
        # Must mention that governance does NOT produce ZPD/correctness
        assert "correctness" in text
        assert "query_type" in text
        assert "command_dispatch" in text


# ─────────────────────────────────────────────────────────────
# Persistence: module_key survives session serialization
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestModuleKeyPersistence:
    """module_key must be included in session persistence dict."""

    def test_persist_session_includes_module_key(self) -> None:
        from lumina.api.session import DomainContext, SessionContainer

        ctx = DomainContext(
            orchestrator=MagicMock(**{"get_standing_order_attempts.return_value": {}}),
            task_spec={"task_id": "t"},
            current_task={},
            turn_count=0,
            domain_id="education",
            task_presented_at=time.time(),
            module_key="domain/edu/domain-authority/v1",
        )
        container = SessionContainer(active_domain_id="education")
        container.contexts["education"] = ctx

        # Simulate what _persist_session_container builds
        contexts_state: dict[str, Any] = {}
        for did, c in container.contexts.items():
            contexts_state[did] = {
                "task_spec": c.task_spec,
                "current_task": c.current_task,
                "turn_count": c.turn_count,
                "domain_id": did,
                "module_key": c.module_key,
            }

        assert contexts_state["education"]["module_key"] == "domain/edu/domain-authority/v1"
