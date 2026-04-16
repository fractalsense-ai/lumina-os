"""Tests for Bug 1 (inspection pipeline invariant source) and Bug 2 (verification_request template).

Bug 1: processing.py was loading invariants from runtime["domain"] (the default
       fallback physics) instead of domain_physics (the module-specific physics
       from the orchestrator). This meant module-level invariants were silently
       skipped by the inspection gate.

Bug 2: The deterministic_templates map had no entry for "verification_request",
       so the fallback "default" template was used — which does NOT instruct
       the LLM to ask for substitution-verification.
"""

from __future__ import annotations

import yaml
from pathlib import Path

import pytest

from lumina.api.runtime_helpers import render_contract_response

REPO = Path(__file__).resolve().parents[1]
RUNTIME_CFG = REPO / "domain-packs" / "education" / "cfg" / "runtime-config.yaml"


# ── Bug 2 regression: verification_request deterministic templates ─────


class TestVerificationRequestTemplate:
    """Ensure verification_request has an explicit deterministic template."""

    @pytest.fixture()
    def runtime(self):
        raw = yaml.safe_load(RUNTIME_CFG.read_text(encoding="utf-8"))
        cfg = raw.get("runtime", raw)
        return cfg

    def test_verification_request_has_template(self, runtime):
        templates = runtime.get("deterministic_templates", {})
        assert "verification_request" in templates, (
            "deterministic_templates must include 'verification_request' "
            "so the LLM/deterministic path instructs the student to substitute"
        )

    def test_verification_request_template_mentions_substitute(self, runtime):
        templates = runtime.get("deterministic_templates", {})
        tmpl = templates.get("verification_request", "")
        assert "substitut" in tmpl.lower(), (
            "verification_request template should instruct the student to "
            "substitute their answer back into the equation"
        )

    def test_render_verification_request_not_default(self, runtime):
        contract = {"prompt_type": "verification_request", "task_id": "3x+1=7"}
        result = render_contract_response(contract, runtime)
        default_template = (runtime.get("deterministic_templates", {}).get("default") or "").format(
            task_id="3x+1=7", prompt_type="verification_request",
        )
        assert result != default_template, (
            "verification_request should NOT fall through to the default template"
        )

    def test_render_verification_request_contains_task_id(self, runtime):
        contract = {"prompt_type": "verification_request", "task_id": "2x+5=11"}
        result = render_contract_response(contract, runtime)
        assert "2x+5=11" in result

    def test_verification_request_mud_template_exists(self, runtime):
        mud_templates = runtime.get("deterministic_templates_mud", {})
        assert "verification_request" in mud_templates, (
            "deterministic_templates_mud must include 'verification_request'"
        )

    def test_verification_request_mud_template_mentions_substitute(self, runtime):
        mud_templates = runtime.get("deterministic_templates_mud", {})
        tmpl = mud_templates.get("verification_request", "")
        assert "substitut" in tmpl.lower()


# ── Bug 1 regression: inspection pipeline invariant source ─────────────


class TestInvariantSourceUsesModulePhysics:
    """Verify that the inspection pipeline receives module-specific invariants,
    not the default-domain invariant list.

    The actual wiring is in processing.py; we test indirectly by reading the
    source line that was fixed.
    """

    def test_processing_uses_domain_physics_for_invariants(self):
        """The _domain_invariants variable must be derived from domain_physics,
        not from runtime.get('domain')."""
        src = (REPO / "src" / "lumina" / "api" / "processing.py").read_text(encoding="utf-8")

        # The buggy line was:
        #   _domain_invariants = (runtime.get("domain") or {}).get("invariants", [])
        # The fix is:
        #   _domain_invariants = domain_physics.get("invariants", [])
        assert 'domain_physics.get("invariants"' in src, (
            "processing.py must load _domain_invariants from domain_physics "
            "(module-specific), not from runtime.get('domain') (default fallback)"
        )

        # Make sure the old buggy pattern is gone
        assert '(runtime.get("domain") or {}).get("invariants"' not in src, (
            "The old buggy invariant source (runtime['domain']) must be removed"
        )


# ── Action-prompt-type map completeness ────────────────────────────────


class TestActionPromptTypeMapCompleteness:
    """Ensure standing-order-driven actions that map to a prompt_type
    also have a deterministic template entry.

    Only checks actions that originate from invariant violations
    (standing_order_on_violation), since those are the ones the student
    hits when the system needs to redirect behaviour.
    """

    @pytest.fixture()
    def runtime(self):
        raw = yaml.safe_load(RUNTIME_CFG.read_text(encoding="utf-8"))
        return raw.get("runtime", raw)

    def test_standing_order_prompt_types_have_templates(self, runtime):
        """Every standing-order action that maps to a prompt_type must have
        a deterministic template so the fallback path gives a meaningful
        instruction — not the generic 'Continue with {task_id}'."""
        action_map = runtime.get("action_prompt_type_map", {})
        templates = runtime.get("deterministic_templates", {})
        tool_policies = runtime.get("tool_call_policies", {})
        # Standing-order-driven actions are those with tool_call_policies entries
        # or whose names start with 'request_' / 'hint_' / 'trigger_'.
        so_prefixes = ("request_", "hint_", "trigger_")
        so_actions = set(tool_policies.keys())
        for action in action_map:
            if any(action.startswith(p) for p in so_prefixes):
                so_actions.add(action)
        missing = []
        for action in so_actions:
            prompt_type = action_map.get(action)
            if prompt_type and prompt_type not in templates:
                missing.append(f"{action} -> {prompt_type}")
        assert not missing, (
            f"These standing-order action->prompt_type mappings lack "
            f"deterministic templates: {missing}"
        )
