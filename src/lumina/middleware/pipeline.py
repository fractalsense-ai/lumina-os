"""Inspection Pipeline — the deterministic boundary between LLM output and execution.

Chains three inspection stages:

1. **NLP Preprocess** — deterministic signal extraction from raw input
2. **Schema Validate** — turn_input_schema conformance check
3. **Invariant Check** — domain physics invariant evaluation

If any stage produces a critical violation the pipeline denies execution.
The ``InspectionResult`` carries the full audit trail for System Log logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from lumina.middleware.invariant_checker import evaluate_invariants
from lumina.middleware.nlp_preprocessor import (
    NLPExtractorFn,
    NLPPreprocessResult,
    run_extractors,
)
from lumina.middleware.output_validator import sanitize_output, validate_output

log = logging.getLogger("lumina.middleware.pipeline")


@dataclass(frozen=True)
class InspectionResult:
    """Immutable outcome of an InspectionPipeline run."""

    approved: bool
    violations: list[str] = field(default_factory=list)
    sanitized_payload: dict[str, Any] = field(default_factory=dict)
    invariant_results: list[dict[str, Any]] = field(default_factory=list)
    nlp_result: NLPPreprocessResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for System Log metadata."""
        return {
            "approved": self.approved,
            "violations": list(self.violations),
            "invariant_summary": [
                {"id": r["id"], "passed": r["passed"], "severity": r["severity"]}
                for r in self.invariant_results
            ],
            "nlp_anchors": (
                [
                    {"key": a.key, "value": a.value}
                    for a in self.nlp_result.anchors
                ]
                if self.nlp_result
                else []
            ),
        }


class InspectionPipeline:
    """Three-stage pipeline: NLP preprocess → schema validate → invariant check.

    Parameters
    ----------
    turn_input_schema:
        Schema descriptor for LLM output validation (from runtime-config).
    invariants:
        List of invariant definitions from domain physics.
    nlp_extractors:
        Optional list of Phase A NLP extractor callables.
    strict:
        When ``True`` (default), any schema violation causes denial.
        When ``False``, schema violations are warnings only — useful for
        graceful degradation during development.
    """

    def __init__(
        self,
        turn_input_schema: dict[str, Any] | None = None,
        invariants: list[dict[str, Any]] | None = None,
        nlp_extractors: list[NLPExtractorFn] | None = None,
        strict: bool = True,
    ) -> None:
        self._schema = turn_input_schema or {}
        self._invariants = invariants or []
        self._extractors = nlp_extractors or []
        self._strict = strict

    def run(
        self,
        payload: dict[str, Any],
        input_text: str = "",
        task_context: dict[str, Any] | None = None,
    ) -> InspectionResult:
        """Execute all inspection stages and return the verdict.

        Parameters
        ----------
        payload:
            The LLM-generated turn_data / evidence dict.
        input_text:
            Raw user input text for NLP pre-processing.
        task_context:
            Optional task context passed to NLP extractors.
        """
        all_violations: list[str] = []

        # ── Stage 1: NLP Pre-Processing ──
        nlp_result: NLPPreprocessResult | None = None
        if self._extractors:
            nlp_result = run_extractors(
                input_text, task_context or {}, self._extractors
            )
            # Merge NLP anchors into payload (NLP doesn't override LLM)
            payload = nlp_result.merge_into(payload)

        # ── Stage 2: Schema Validation ──
        if self._schema:
            valid, schema_violations = validate_output(payload, self._schema)
            if not valid:
                all_violations.extend(schema_violations)
                if self._strict:
                    log.warning(
                        "Schema validation failed: %s", schema_violations
                    )
            # Fill defaults for missing optional fields
            payload = sanitize_output(payload, self._schema)

        # ── Stage 3: Invariant Checking ──
        invariant_results: list[dict[str, Any]] = []
        if self._invariants:
            invariant_results = evaluate_invariants(self._invariants, payload)
            for result in invariant_results:
                if not result["passed"]:
                    sev = result["severity"]
                    msg = (
                        f"Invariant '{result['id']}' failed "
                        f"(severity={sev})"
                    )
                    all_violations.append(msg)
                    if sev == "critical":
                        log.warning("Critical invariant failure: %s", msg)

        # ── Verdict ──
        critical_failures = any(
            not r["passed"] and r["severity"] == "critical"
            for r in invariant_results
        )
        schema_blocked = (
            self._strict and any(v.startswith("Missing required") or v.startswith("Type mismatch") for v in all_violations)
        )
        approved = not critical_failures and not schema_blocked

        return InspectionResult(
            approved=approved,
            violations=all_violations,
            sanitized_payload=payload,
            invariant_results=invariant_results,
            nlp_result=nlp_result,
        )
