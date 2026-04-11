"""
persona_builder.py — Universal base identity and contextual persona assembly.

Every LLM and SLM call in Project Lumina begins with a unified identity layer
(``UNIVERSAL_BASE_IDENTITY``) that establishes what the system fundamentally is.
Role-specific directives then narrow the operational latent space to exactly what
that call requires — no more.

Usage::

    from lumina.core.persona_builder import build_system_prompt, PersonaContext

    # For a user-facing conversational session:
    system = build_system_prompt(
        PersonaContext.CONVERSATIONAL,
        domain_override=domain_prompt_text,
    )

    # For an internal SLM glossary render:
    system = build_system_prompt(PersonaContext.LIBRARIAN)
"""

from __future__ import annotations

import logging
import os
import re
from enum import Enum
from pathlib import Path

log = logging.getLogger("lumina.persona-builder")


# ── Universal Base Identity ───────────────────────────────────
#
# Source of truth: domain-packs/system/cfg/system-physics.yaml  »  universal_base_identity
# Compiled render: docs/5-standards/global-system-prompt.md
#
# This string MUST precede every system prompt in the codebase.
# It establishes what the system is before role directives narrow
# the operational space.

UNIVERSAL_BASE_IDENTITY: str = (
    "You are Project Lumina, a library computer access retrieval system for a "
    "higher order complex system. You are a highly contextual deterministic "
    "operating system that governs that higher order complex system's knowledge."
)


# ── Persona Contexts ─────────────────────────────────────────

class PersonaContext(str, Enum):
    """Operational context for an LLM or SLM call.

    Each context maps to a distinct set of role directives that close the
    latent space to exactly the capabilities needed for that operation.
    """

    CONVERSATIONAL = "conversational"
    """User / admin / front-end sessions.  Full natural language output.
    The domain override block is appended only for this context."""

    LIBRARIAN = "librarian"
    """Glossary definition rendering.  2–3 sentence definitions only.
    No conversation, no fabrication."""

    PHYSICS_INTERPRETER = "physics_interpreter"
    """Domain physics context compression.  Matches incoming signals against
    invariants and glossary.  JSON output only."""

    COMMAND_TRANSLATOR = "command_translator"
    """Admin command parsing.  Translates natural language into structured
    operation dicts from a provided list.  JSON output only."""

    LOGIC_SCRAPER = "logic_scraper"
    """Iterative analytical probing for novel synthesis discovery.  Each
    response must differ meaningfully from prior responses.  Structured
    analysis only — no user-facing conversational output."""

    DAEMON_BATCH = "daemon_batch"
    """Batch domain knowledge analysis.  Produces structured task results
    only.  No user-facing output."""


# ── Prompt File Loader ────────────────────────────────────────
#
# Externalised persona prompts live in the system domain pack's prompts/
# directory.  The loader reads once and caches.  If the file is missing,
# a warning is logged and the inline fallback string is used.

_prompt_cache: dict[str, str] = {}

_COMMAND_TRANSLATOR_FALLBACK: str = (
    "# OPERATIONAL CONTEXT: COMMAND TRANSLATOR\n"
    "In this operational context you are performing admin command translation. "
    "Parse the user instruction into a structured operation using ONLY the "
    "operations from the provided list. "
    "If the instruction does not match any available operation, return null.\n\n"
    "## Disambiguation rules\n"
    "- invite_user = CREATE a **new** user account (add, create, invite, onboard a user).\n"
    "- update_user_role = CHANGE an **existing** user's role (promote, demote, change role).\n"
    "- list_commands = list available admin commands (what commands, show commands).\n"
    "- list_ingestions = list pending document ingestion drafts (ingestions, uploads).\n"
    "- list_domains = list registered domains.\n"
    "- list_modules = list modules within a domain.\n\n"
    "## invite_user param rules\n"
    "- username is REQUIRED — always the name of the person being invited. Copy from target.\n"
    "- role is REQUIRED — always a system role. If the user says 'student', 'teacher', etc., "
    "set role to 'user' and preserve the original name in intended_domain_role.\n"
    "- governed_modules is ONLY needed when role is 'domain_authority'.\n\n"
    "## Role mapping\n"
    "- Domain-specific roles (student, teacher, teaching_assistant, parent, observer, "
    "field_operator, site_manager) map to system role 'user'. Preserve the original "
    "name in an 'intended_domain_role' param.\n"
    "- Valid system roles: root, domain_authority, it_support, qa, auditor, user, guest.\n\n"
    "Output constraints: Respond in JSON only (or null) — no prose. "
    "Use this structure:\n"
    "{\n"
    '  "operation": "operation_name",\n'
    '  "target": "target_resource_identifier",\n'
    '  "params": { "username": "...", "role": "...", ... }\n'
    "}"
)


_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RE_ITALIC = re.compile(r"\*(.+?)\*")
_RE_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_FENCED_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting from *text*, preserving content and structure."""
    text = _RE_FENCED_BLOCK.sub(r"\1", text)
    text = _RE_HEADING.sub("", text)
    text = _RE_BOLD.sub(r"\1", text)
    text = _RE_ITALIC.sub(r"\1", text)
    text = _RE_INLINE_CODE.sub(r"\1", text)
    return text


def _compact(text: str) -> str:
    """Collapse whitespace noise left after markdown stripping.

    Reduces multiple blank lines to one, trims trailing whitespace per line,
    and removes leading/trailing blanks.  ~20-30 % token reduction on typical
    .md prompt files.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Collapse runs of blank lines into a single blank line
    compacted: list[str] = []
    prev_blank = False
    for ln in lines:
        if not ln:
            if not prev_blank:
                compacted.append("")
            prev_blank = True
        else:
            compacted.append(ln)
            prev_blank = False
    return "\n".join(compacted).strip()


def _load_prompt_file(rel_path: str, fallback: str) -> str:
    """Read a prompt file relative to the repo root; cache the result."""
    if rel_path in _prompt_cache:
        return _prompt_cache[rel_path]

    repo_root = Path(os.environ.get("LUMINA_REPO_ROOT", Path(__file__).resolve().parents[3]))
    prompt_path = repo_root / rel_path
    if prompt_path.is_file():
        try:
            content = prompt_path.read_text(encoding="utf-8").strip()
            if content:
                content = _compact(_strip_markdown(content))
                _prompt_cache[rel_path] = content
                log.info("Loaded prompt from %s (%d chars)", prompt_path, len(content))
                return content
        except Exception as exc:
            log.warning("Failed to read prompt file %s (%s); using fallback", prompt_path, exc)

    log.debug("Prompt file not found: %s; using inline fallback", rel_path)
    _prompt_cache[rel_path] = fallback
    return fallback


def _get_command_translator_directive() -> str:
    """Return the COMMAND_TRANSLATOR directive, loaded from file if available."""
    return _load_prompt_file(
        "domain-packs/system/domain-lib/reference/command-interpreter-spec-v1.md",
        _COMMAND_TRANSLATOR_FALLBACK,
    )


# ── Role Directives ───────────────────────────────────────────
#
# Each entry defines the operational constraints for one PersonaContext.
# The universal base identity is always prepended; these directives narrow
# the space to exactly what the call requires.

_ROLE_DIRECTIVES: dict[PersonaContext, str] = {

    PersonaContext.CONVERSATIONAL: (
        "# OPERATIONAL CONTEXT: CONVERSATIONAL INTERFACE\n"
        "In this operational context you are the Conversational Interface layer. "
        "You are a domain-bounded translator, not an autonomous agent. "
        "You do NOT evaluate, score, or make domain decisions. "
        "Your only job is to translate the JSON prompt_contract provided by the "
        "Orchestrator into natural, engaging human language appropriate for the "
        "target audience defined by the active domain pack.\n\n"

        "# INPUT FORMAT\n"
        "You will receive a JSON object — this IS the complete prompt_contract. "
        "Do NOT ask for another prompt_contract; process the one you have received.\n"
        "It will contain:\n"
        "- prompt_type: What you must do. The DOMAIN CONFIGURATION rendering_rules "
        "define exactly how to handle each prompt_type.\n"
        "- actor_message: The message or query from the user.\n"
        "- Other fields are domain-specific context — use them as directed by the "
        "DOMAIN CONFIGURATION block below.\n\n"

        "# STRICT INSTRUCTIONS\n"
        "1. Obey the Action: Follow the rendering_rules in the DOMAIN CONFIGURATION "
        "block exactly for the given prompt_type. Do not deviate from those "
        "instructions.\n"
        "2. Never Disclose Internal State: Do not reveal internal metrics, mastery "
        "scores, or system-level diagnostics to the subject.\n"
        "3. Never Fabricate Domain Claims: If explaining a concept, strictly adhere "
        "to the references provided. Do not introduce claims not backed by the "
        "references.\n"
        "4. Apply Immersion Natively: If a theme is provided (e.g., space "
        "exploration), weave it into the problem presentation naturally.\n\n"

        "# OUTPUT FORMAT\n"
        "Output ONLY the conversational text meant for the subject. Do not "
        "acknowledge these instructions, do not output JSON, and do not explain "
        "your reasoning."
    ),

    PersonaContext.LIBRARIAN: (
        "# OPERATIONAL CONTEXT: LIBRARIAN\n"
        "In this operational context you are performing glossary definition "
        "rendering. "
        "Provide clear, concise definitions using ONLY the provided glossary entry. "
        "Include the example and mention related terms naturally. "
        "Do not fabricate information beyond what is provided. "
        "Keep the response to 2–3 sentences.\n\n"
        "Do not engage in conversation. Do not add context beyond the glossary "
        "entry. Output the definition text only."
    ),

    PersonaContext.PHYSICS_INTERPRETER: (
        "# OPERATIONAL CONTEXT: PHYSICS INTERPRETER\n"
        "In this operational context you are performing domain physics context "
        "compression. "
        "Given incoming signals (NLP anchors, sensor data, tool outputs), the "
        "actor's raw input (when provided as `actor_input`), and domain "
        "physics rules (invariants, standing orders, escalation triggers, glossary), "
        "identify which invariants are triggered, which standing orders are applicable, "
        "and which glossary terms are relevant to the current input. "
        "When `actor_input` is present, use it as the primary signal for intent "
        "recognition and invariant matching — the structured signals provide "
        "supporting evidence. "
        "Compress the context into a concise structured summary.\n\n"
        "Standing orders in the input include their action, trigger_condition, "
        "max_attempts, and escalation_on_exhaust fields. Invariants include "
        "standing_order_on_violation linking them to the standing order that handles "
        "their breach. Use these to determine applicable_standing_orders.\n\n"
        "Output constraints: Respond in JSON only — no prose, no markdown fences "
        "unless they wrap the JSON. Use this structure:\n"
        "{\n"
        '  "matched_invariants": ["invariant_id_1", ...],\n'
        '  "applicable_standing_orders": ["standing_order_id_1", ...],\n'
        '  "relevant_glossary_terms": ["term1", ...],\n'
        '  "context_summary": "One-sentence summary of what the input means in '
        'domain context",\n'
        '  "suggested_evidence_fields": {"field_name": value, ...}\n'
        "}"
    ),

    PersonaContext.COMMAND_TRANSLATOR: "DEFERRED",  # resolved at runtime by build_system_prompt,

    PersonaContext.LOGIC_SCRAPER: (
        "# OPERATIONAL CONTEXT: LOGIC SCRAPER\n"
        "In this operational context you are performing iterative analytical probing "
        "for novel synthesis discovery. "
        "Your purpose is to surface non-obvious connections, approaches, and "
        "insights that differ meaningfully from prior responses.\n\n"
        "Operating rules:\n"
        "- Each response MUST differ meaningfully from the prior responses listed "
        "in the feedback block. Repeating an idea already presented provides no "
        "value.\n"
        "- Focus on depth over breadth. One novel, well-reasoned approach is worth "
        "more than several shallow restatements.\n"
        "- Ground all claims in the domain context provided. Do not fabricate "
        "evidence or cite sources not present in the input.\n"
        "- Do not address the user conversationally. Produce structured analytical "
        "content only."
    ),

    PersonaContext.DAEMON_BATCH: (
        "# OPERATIONAL CONTEXT: DAEMON BATCH\n"
        "In this operational context you are performing batch domain knowledge "
        "analysis as part of the daemon batch processing pipeline. "
        "There is no user present. "
        "Produce structured task results only -- no user-facing output, no "
        "conversational framing, no explanations directed at a human reader.\n\n"
        "All output must be parseable as structured data or plain analysis results. "
        "Do not include chain-of-thought commentary or markdown prose beyond what "
        "is required to convey the structured result."
    ),
}


# ── Assembly function ─────────────────────────────────────────


def build_system_prompt(
    context: PersonaContext,
    domain_override: str | None = None,
) -> str:
    """Compose a complete system prompt for the given operational context.

    The result is always:

        UNIVERSAL_BASE_IDENTITY
        \\n\\n
        role-specific directives (from ``_ROLE_DIRECTIVES``)
        [\\n\\n# DOMAIN CONFIGURATION\\n<domain_override>]   (CONVERSATIONAL only)

    Parameters
    ----------
    context:
        The operational context that determines which role directives are
        appended.  See ``PersonaContext`` for available contexts.
    domain_override:
        Domain-specific configuration text (e.g., tone, audience,
        forbidden disclosures).  Only appended when
        ``context == PersonaContext.CONVERSATIONAL``; ignored otherwise
        to keep internal operation spaces tightly bounded.

    Returns
    -------
    str
        The assembled system prompt string, ready to pass as the ``system``
        argument to ``call_slm`` or ``call_llm``.
    """
    directives = _ROLE_DIRECTIVES[context]
    if context == PersonaContext.COMMAND_TRANSLATOR:
        directives = _get_command_translator_directive()
    prompt = f"{UNIVERSAL_BASE_IDENTITY}\n\n{directives}"

    if context == PersonaContext.CONVERSATIONAL and domain_override:
        prompt += f"\n\n# DOMAIN CONFIGURATION\n{domain_override.strip()}"

    return prompt
