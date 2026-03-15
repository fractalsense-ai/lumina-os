"""Tests for lumina.core.persona_builder — universal identity and persona assembly.

Verifies that every operational context builds on the universal base identity,
that role-specific directives correctly constrain (or open) the latent space,
and that domain overrides are only appended for the CONVERSATIONAL context.
"""

from __future__ import annotations

from unittest.mock import call, patch

import pytest

from lumina.core.persona_builder import (
    UNIVERSAL_BASE_IDENTITY,
    PersonaContext,
    build_system_prompt,
)


# ── Universal Base Identity ───────────────────────────────────────────────────


class TestUniversalBaseIdentity:

    @pytest.mark.unit
    def test_identity_is_non_empty(self) -> None:
        assert UNIVERSAL_BASE_IDENTITY.strip()

    @pytest.mark.unit
    def test_identity_references_library_system(self) -> None:
        assert "library computer" in UNIVERSAL_BASE_IDENTITY.lower()

    @pytest.mark.unit
    def test_identity_references_deterministic_os(self) -> None:
        assert "deterministic operating system" in UNIVERSAL_BASE_IDENTITY.lower()

    @pytest.mark.unit
    def test_universal_base_identity_in_all_contexts(self) -> None:
        """Every context's system prompt must begin with the universal base identity."""
        for context in PersonaContext:
            prompt = build_system_prompt(context)
            assert prompt.startswith(UNIVERSAL_BASE_IDENTITY), (
                f"PersonaContext.{context.value} prompt does not start with "
                "UNIVERSAL_BASE_IDENTITY"
            )


# ── Domain Override Behaviour ─────────────────────────────────────────────────


class TestDomainOverride:

    @pytest.mark.unit
    def test_conversational_appends_domain_override(self) -> None:
        override = "target_audience: adult operators\ntone_profile: concise"
        prompt = build_system_prompt(PersonaContext.CONVERSATIONAL, domain_override=override)
        assert "# DOMAIN CONFIGURATION" in prompt
        assert override in prompt

    @pytest.mark.unit
    def test_conversational_no_override_no_domain_block(self) -> None:
        prompt = build_system_prompt(PersonaContext.CONVERSATIONAL)
        assert "# DOMAIN CONFIGURATION" not in prompt

    @pytest.mark.unit
    def test_non_conversational_contexts_ignore_domain_override(self) -> None:
        """Domain overrides must NOT leak into internal operation spaces."""
        override = "secret_audience_config: xyz"
        internal_contexts = [
            PersonaContext.LIBRARIAN,
            PersonaContext.PHYSICS_INTERPRETER,
            PersonaContext.COMMAND_TRANSLATOR,
            PersonaContext.LOGIC_SCRAPER,
            PersonaContext.NIGHT_CYCLE,
        ]
        for context in internal_contexts:
            prompt = build_system_prompt(context, domain_override=override)
            assert "# DOMAIN CONFIGURATION" not in prompt, (
                f"Domain override block found in {context.value} context"
            )
            assert override not in prompt, (
                f"Domain override content leaked into {context.value} context"
            )

    @pytest.mark.unit
    def test_domain_override_stripped(self) -> None:
        """Leading/trailing whitespace in domain override is stripped."""
        override = "  \n  tone_profile: brief  \n  "
        prompt = build_system_prompt(PersonaContext.CONVERSATIONAL, domain_override=override)
        assert "tone_profile: brief" in prompt
        # Should not double-add blank lines from whitespace
        assert "# DOMAIN CONFIGURATION\ntone_profile" in prompt


# ── Role-Specific Directives ──────────────────────────────────────────────────


class TestConversationalDirectives:

    @pytest.mark.unit
    def test_conversational_allows_natural_language_output(self) -> None:
        prompt = build_system_prompt(PersonaContext.CONVERSATIONAL)
        assert "conversational" in prompt.lower() or "natural" in prompt.lower()

    @pytest.mark.unit
    def test_conversational_references_prompt_contract(self) -> None:
        prompt = build_system_prompt(PersonaContext.CONVERSATIONAL)
        assert "prompt_contract" in prompt or "prompt contract" in prompt.lower()

    @pytest.mark.unit
    def test_conversational_references_operational_context(self) -> None:
        prompt = build_system_prompt(PersonaContext.CONVERSATIONAL)
        assert "OPERATIONAL CONTEXT" in prompt


class TestLibrarianDirectives:

    @pytest.mark.unit
    def test_librarian_restricts_to_glossary_only(self) -> None:
        prompt = build_system_prompt(PersonaContext.LIBRARIAN)
        assert "glossary" in prompt.lower() or "definition" in prompt.lower()

    @pytest.mark.unit
    def test_librarian_prohibits_fabrication(self) -> None:
        prompt = build_system_prompt(PersonaContext.LIBRARIAN)
        assert "fabricat" in prompt.lower() or "only" in prompt.lower()

    @pytest.mark.unit
    def test_librarian_no_conversational_turn_instructions(self) -> None:
        """Librarian context must not include CI turn-translation instructions."""
        prompt = build_system_prompt(PersonaContext.LIBRARIAN)
        assert "prompt_contract" not in prompt
        assert "prompt_type" not in prompt


class TestPhysicsInterpreterDirectives:

    @pytest.mark.unit
    def test_physics_interpreter_json_only(self) -> None:
        prompt = build_system_prompt(PersonaContext.PHYSICS_INTERPRETER)
        assert "json" in prompt.lower()

    @pytest.mark.unit
    def test_physics_interpreter_references_invariants(self) -> None:
        prompt = build_system_prompt(PersonaContext.PHYSICS_INTERPRETER)
        assert "invariant" in prompt.lower()

    @pytest.mark.unit
    def test_physics_interpreter_references_context_compression(self) -> None:
        prompt = build_system_prompt(PersonaContext.PHYSICS_INTERPRETER)
        assert "compress" in prompt.lower() or "context" in prompt.lower()


class TestCommandTranslatorDirectives:

    @pytest.mark.unit
    def test_command_translator_json_only(self) -> None:
        prompt = build_system_prompt(PersonaContext.COMMAND_TRANSLATOR)
        assert "json" in prompt.lower()

    @pytest.mark.unit
    def test_command_translator_references_operations_list(self) -> None:
        prompt = build_system_prompt(PersonaContext.COMMAND_TRANSLATOR)
        assert "operation" in prompt.lower()

    @pytest.mark.unit
    def test_command_translator_handles_null_case(self) -> None:
        """Must mention returning null when no operation matches."""
        prompt = build_system_prompt(PersonaContext.COMMAND_TRANSLATOR)
        assert "null" in prompt.lower()


class TestLogicScraperDirectives:

    @pytest.mark.unit
    def test_logic_scraper_anti_repetition_directive(self) -> None:
        prompt = build_system_prompt(PersonaContext.LOGIC_SCRAPER)
        # Must instruct model to differ from prior responses
        assert "differ" in prompt.lower() or "not repeat" in prompt.lower()

    @pytest.mark.unit
    def test_logic_scraper_novel_synthesis_framing(self) -> None:
        prompt = build_system_prompt(PersonaContext.LOGIC_SCRAPER)
        assert "novel" in prompt.lower() or "non-obvious" in prompt.lower()

    @pytest.mark.unit
    def test_logic_scraper_no_conversational_output(self) -> None:
        prompt = build_system_prompt(PersonaContext.LOGIC_SCRAPER)
        # Must not contain CI conversational turn-translation instructions
        assert "prompt_type" not in prompt
        assert "prompt_contract" not in prompt


class TestNightCycleDirectives:

    @pytest.mark.unit
    def test_night_cycle_no_user_facing_output(self) -> None:
        prompt = build_system_prompt(PersonaContext.NIGHT_CYCLE)
        assert "no user-facing" in prompt.lower() or "user-facing" in prompt.lower()

    @pytest.mark.unit
    def test_night_cycle_structured_results(self) -> None:
        prompt = build_system_prompt(PersonaContext.NIGHT_CYCLE)
        assert "structured" in prompt.lower()

    @pytest.mark.unit
    def test_night_cycle_no_conversation_instructions(self) -> None:
        prompt = build_system_prompt(PersonaContext.NIGHT_CYCLE)
        assert "prompt_contract" not in prompt


# ── SLM Integration ───────────────────────────────────────────────────────────


class TestSLMPersonaIntegration:

    @pytest.mark.unit
    def test_slm_render_glossary_uses_librarian_persona(self) -> None:
        """slm_render_glossary should call call_slm with the LIBRARIAN persona."""
        from lumina.core.slm import slm_render_glossary
        glossary_entry = {"term": "invariant", "definition": "A rule."}
        expected_system = build_system_prompt(PersonaContext.LIBRARIAN)

        with patch("lumina.core.slm.call_slm", return_value="A rule.") as mock_slm:
            slm_render_glossary(glossary_entry)
            mock_slm.assert_called_once()
            actual_system = mock_slm.call_args.kwargs["system"]
            assert actual_system == expected_system
            assert actual_system.startswith(UNIVERSAL_BASE_IDENTITY)

    @pytest.mark.unit
    def test_slm_interpret_physics_uses_physics_interpreter_persona(self) -> None:
        """slm_interpret_physics_context should call call_slm with the PHYSICS_INTERPRETER persona."""
        from lumina.core.slm import slm_interpret_physics_context
        expected_system = build_system_prompt(PersonaContext.PHYSICS_INTERPRETER)
        slm_response = (
            '{"matched_invariants": [], "relevant_glossary_terms": [], '
            '"context_summary": "", "suggested_evidence_fields": {}}'
        )

        with patch("lumina.core.slm.call_slm", return_value=slm_response) as mock_slm:
            slm_interpret_physics_context({"signal": "x"}, {"invariants": []})
            mock_slm.assert_called_once()
            actual_system = mock_slm.call_args.kwargs["system"]
            assert actual_system == expected_system
            assert actual_system.startswith(UNIVERSAL_BASE_IDENTITY)


# ── Logic Scraper Integration ─────────────────────────────────────────────────


class TestLogicScraperPersonaIntegration:

    @pytest.mark.unit
    def test_logic_scraper_passes_logic_scraper_persona(self) -> None:
        """LogicScraper.scrape() should use the LOGIC_SCRAPER persona as the system prompt."""
        from lumina.tools.logic_scraper import LogicScraper

        expected_system = build_system_prompt(PersonaContext.LOGIC_SCRAPER)
        captured: list[str] = []

        def mock_llm(system: str, user: str) -> str:
            captured.append(system)
            return "A novel response."

        scraper = LogicScraper(
            call_llm_fn=mock_llm,
            domain_physics={"invariants": []},
            config={"max_iterations": 2},
        )
        scraper.scrape("test prompt")

        assert len(captured) >= 1
        assert captured[0] == expected_system
        assert captured[0].startswith(UNIVERSAL_BASE_IDENTITY)
