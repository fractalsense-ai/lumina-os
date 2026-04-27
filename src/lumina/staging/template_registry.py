"""Template Registry — maps template_id → blank templates with metadata.

Each template defines:
  - ``required_fields``  — keys that *must* appear in the staged payload
  - ``default_structure`` — skeleton dict merged with the payload
  - ``target_pattern``   — string pattern for the final file path
                           (placeholders like ``{domain_id}``, ``{name}``)
  - ``file_format``      — ``"json"`` or ``"yaml"``

The set of known template IDs is intentionally small and grows only when
a new file *type* is added to the project standards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Template:
    """Immutable descriptor for one file template."""

    template_id: str
    description: str
    required_fields: tuple[str, ...]
    default_structure: dict[str, Any]
    target_pattern: str
    file_format: str = "json"          # "json" | "yaml"


# ------------------------------------------------------------------
# Built-in templates
# ------------------------------------------------------------------

_TEMPLATES: dict[str, Template] = {}


def _register(t: Template) -> None:
    _TEMPLATES[t.template_id] = t


_register(Template(
    template_id="domain-physics",
    description="New or updated domain-physics.json file",
    required_fields=("id", "version", "admin", "invariants",
                     "standing_orders", "escalation_triggers", "artifacts"),
    default_structure={
        "meta_authority_id": "",
        "description": "",
        "lumina_core_version": "1.0",
        "subsystem_configs": {},
        "glossary": [],
    },
    target_pattern="model-packs/{domain_short}/cfg/domain-physics.json",
    file_format="json",
))

_register(Template(
    template_id="evidence-schema",
    description="New domain evidence-schema.json file",
    required_fields=("schema_id", "version", "domain_id", "fields"),
    default_structure={
        "description": "",
    },
    target_pattern="model-packs/{domain_short}/cfg/evidence-schema.json",
    file_format="json",
))

_register(Template(
    template_id="tool-adapter",
    description="New tool adapter YAML definition",
    required_fields=("id", "version", "tool_name", "description",
                     "domain_id", "input_schema", "output_schema"),
    default_structure={
        "call_types": [],
        "authorization": {
            "who_may_call": ["orchestrator"],
            "requires_entity_consent": False,
            "max_calls_per_session": None,
            "logged_in_system_log": True,
        },
        "error_handling": {
            "on_failure": "escalate",
            "fallback_standing_order_id": None,
        },
    },
    target_pattern="model-packs/{domain_short}/modules/{module}/tool-adapters/{adapter_name}-adapter-v{major}.yaml",
    file_format="yaml",
))

_register(Template(
    template_id="student-profile",
    description="New student/entity profile YAML",
    required_fields=("profile_id", "entity_name", "domain_id"),
    default_structure={
        "mastery": {},
        "history": [],
        "preferences": {},
    },
    target_pattern="model-packs/{domain_short}/profiles/{profile_id}.yaml",
    file_format="yaml",
))

_register(Template(
    template_id="context-hint",
    description="Context hint generated during daemon batch",
    required_fields=("hint_id", "domain_id", "content"),
    default_structure={
        "source_task": "context_crawler",
        "confidence": 0.0,
        "tags": [],
    },
    target_pattern="model-packs/{domain_short}/context-hints/{hint_id}.json",
    file_format="json",
))


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

class TemplateRegistry:
    """Read-only registry of known file templates."""

    @staticmethod
    def get(template_id: str) -> Template | None:
        return _TEMPLATES.get(template_id)

    @staticmethod
    def require(template_id: str) -> Template:
        t = _TEMPLATES.get(template_id)
        if t is None:
            raise ValueError(f"Unknown template_id: {template_id!r}")
        return t

    @staticmethod
    def list_ids() -> frozenset[str]:
        return frozenset(_TEMPLATES)

    @staticmethod
    def all_templates() -> dict[str, Template]:
        return dict(_TEMPLATES)
