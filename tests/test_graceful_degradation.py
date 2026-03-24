"""Tests for graceful degradation — clarification response builder.

When the auto-stage pipeline fails (schema validation, unknown role, etc.)
the system should return a structured clarification card rather than a
bare HTTP error, giving the user actionable hints to fix the command.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Clarification response structure ─────────────────────────────────────────


@pytest.mark.integration
def test_clarification_response_structure() -> None:
    """_build_clarification_response should return a well-formed action card."""
    from lumina.api.processing import _build_clarification_response

    result = _build_clarification_response(
        error_msg="Something went wrong",
        cmd_dispatch={"operation": "update_user_role", "params": {"user_id": "bob"}},
        user=None,
    )
    assert result["type"] == "action_card"
    assert result["card_type"] == "clarification_needed"
    assert result["operation"] == "update_user_role"
    assert result["error"] == "Something went wrong"
    assert isinstance(result["hints"], list)
    assert len(result["hints"]) > 0


@pytest.mark.integration
def test_clarification_for_invalid_role() -> None:
    """When schema validation fails with a domain role, hints should suggest 'user'."""
    from lumina.api.processing import _build_clarification_response

    result = _build_clarification_response(
        error_msg="Command schema validation failed: new_role not in VALID_ROLES",
        cmd_dispatch={
            "operation": "update_user_role",
            "params": {"user_id": "bob", "new_role": "student"},
        },
        user=None,
    )
    assert result["card_type"] == "clarification_needed"
    hints_text = " ".join(result["hints"]).lower()
    assert "domain role" in hints_text
    assert "user" in hints_text


@pytest.mark.integration
def test_clarification_for_empty_governed_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty governed_modules should trigger a hint listing available domains."""
    from lumina.api import config as _cfg
    from lumina.api.processing import _build_clarification_response

    mock_registry = MagicMock()
    mock_registry.list_domains.return_value = [
        {"domain_id": "education", "label": "Education"},
        {"domain_id": "agriculture", "label": "Agriculture"},
    ]
    monkeypatch.setattr(_cfg, "DOMAIN_REGISTRY", mock_registry)

    result = _build_clarification_response(
        error_msg="governed_modules cannot be empty",
        cmd_dispatch={
            "operation": "invite_user",
            "params": {"username": "alice", "role": "user", "governed_modules": []},
        },
        user=None,
    )
    assert result["card_type"] == "clarification_needed"
    hints_text = " ".join(result["hints"]).lower()
    assert "education" in hints_text
    assert "agriculture" in hints_text
