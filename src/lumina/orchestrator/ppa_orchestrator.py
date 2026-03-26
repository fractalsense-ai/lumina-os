"""
ppa_orchestrator.py â€” Project Lumina Prompt Packet Assembly (PPA) Orchestrator

Version: 0.4.0
Conforms to: specs/dsa-framework-v1.md
             standards/system-log-v1.md

Implements the Actor layer of the D.S.A. framework as a thin pipeline
coordinator.  Heavy concerns are delegated to three focused collaborators:

    ActorResolver   (the Judge)  — invariant evaluation + action/escalation logic
    ContractDrafter (the Clerk)  â€” prompt-contract assembly
    SystemLogWriter (the Scribe) â€” hash-chained System Log I/O

Pipeline (process_turn)::

    invariant_results  = resolver.check_invariants(evidence)
    domain_lib_decision = _step_domain_lib(task_spec, evidence)
    action, escalate, trigger = resolver.resolve(invariant_results, domain_lib_decision)
    prompt_contract    = drafter.build(task_spec, action, domain_lib_decision, trigger)
    writer.record_turn(...)   # fire-and-wait today; wiring-ready for async later

Backward compatibility:
    All private methods and attributes that tests call directly
    (_resolve_action, _standing_order_attempts, etc.) are preserved as
    one-liner delegates to the appropriate collaborator.

Invariant evaluation (domain-pack-driven):
    Each invariant in the domain-pack may carry a ``check`` field whose value
    is a simple predicate expression referencing flat evidence-dict keys:

        ``<field>``                  â€” truthy check on evidence[field]
        ``<field> == <literal>``     â€” equality check (supports [] / true / false)
        ``<field> != <literal>``     â€” inequality check
        ``<field> >= <number>``      â€” numeric comparison (also >, <, <=)

    Invariants marked with ``"handled_by": "<subsystem>"`` are skipped here
    and delegated entirely to the registered domain lib (or ignored when no
    lib is registered).

Design constraints:
    - Standard library only (no external dependencies in this module).
    - All System Log records are hash-chained with SHA-256 canonical JSON.
    - No domain-specific domain-lib implementation is imported or required.

Usage::

    from lumina.orchestrator.ppa_orchestrator import PPAOrchestrator, load_domain_physics
    domain  = load_domain_physics("domain-packs/education/modules/algebra-level-1/domain-physics.json")
    profile = load_yaml("domain-packs/education/modules/algebra-level-1/example-student-alice.yaml")
    orch    = PPAOrchestrator(domain, profile, ledger_path="session.jsonl")
    contract, action = orch.process_turn(task_spec, evidence)
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Callable

from lumina.orchestrator.actor_resolver import ActorResolver
from lumina.orchestrator.contract_drafter import ContractDrafter
from lumina.orchestrator.system_log_writer import (
    SystemLogWriter,
    canonical_json as _canonical_json,
    hash_record as _hash_record,
    hash_payload as _hash_payload,
)

from lumina.system_log.event_payload import LogLevel, create_event
from lumina.system_log import log_bus

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Logging
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

log = logging.getLogger("ppa_orchestrator")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Module-level re-exports
# (backward compatibility â€” external callers import these from ppa_orchestrator)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def canonical_json(record: dict[str, Any]) -> bytes:
    """Canonical JSON: keys sorted, no whitespace, UTF-8."""
    return _canonical_json(record)


def hash_record(record: dict[str, Any]) -> str:
    """Compute SHA-256 of a canonical System Log record."""
    return _hash_record(record)


def hash_payload(payload: dict[str, Any]) -> str:
    """Hash arbitrary structured payload with canonical JSON rules."""
    return _hash_payload(payload)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Domain Physics Loader
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def load_domain_physics(path: str | Path) -> dict[str, Any]:
    """Load domain physics from a JSON file."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Domain-pack-driven invariant check evaluator
#
# Canonical implementation lives in lumina.middleware.invariant_checker.
# These module-level aliases preserve backward compatibility for external
# callers that import from ppa_orchestrator directly.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

from lumina.middleware.invariant_checker import (
    evaluate_check_expr as _evaluate_check_expr,
    evaluate_invariants as _mw_evaluate_invariants,
    parse_check_literal as _parse_check_literal,
)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PPAOrchestrator â€” thin pipeline coordinator
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class PPAOrchestrator:
    """
    D.S.A. Actor layer orchestrator.

    Connects Domain Physics â†’ (optional domain lib) â†’ System Log â†’ Prompt Contract
    for a single session.  Decision logic, contract formatting, and log I/O are
    each handled by a dedicated collaborator; this class wires them together and
    owns the domain-lib state machine.

    Attributes:
        domain      Domain physics dict loaded from JSON.
        profile     Subject profile dict (domain-agnostic; loaded by the caller).
        state       Current domain-lib state (opaque to the engine).
        session_id  UUID string identifying this session in the System Logs.
    """

    def __init__(
        self,
        domain_physics: dict[str, Any],
        subject_profile: dict[str, Any],
        ledger_path: str | Path,
        session_id: str | None = None,
        domain_lib_step_fn: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
        initial_state: Any | None = None,
        action_prompt_type_map: dict[str, str] | None = None,
        policy_commitment: dict[str, Any] | None = None,
        log_append_callback: Callable[[str, dict[str, Any]], None] | None = None,
        system_physics_hash: str | None = None,
    ) -> None:
        """
        Initialise the orchestrator.

        Args:
            domain_physics:  Domain physics dict (from ``load_domain_physics``).
            subject_profile: Subject profile dict (any domain; load with
                             ``yaml_loader.load_yaml`` or equivalent).
            ledger_path:     Path to the JSONL System Log ledger file.
            session_id:      Optional session UUID; generated if omitted.
            domain_lib_step_fn: Optional domain-lib callable with signature
                             ``(state, task_spec, evidence) -> (new_state, decision_dict)``.
                             Pass ``None`` (default) for domain packs that declare
                             no domain-lib subsystem.
            initial_state:   Initial domain-lib state passed to ``domain_lib_step_fn``
                             on the first turn.  Ignored when ``domain_lib_step_fn``
                             is ``None``.
            action_prompt_type_map: Optional action-to-prompt_type mapping loaded
                             from domain runtime config.
            policy_commitment: Optional policy commitment metadata with authoritative
                             subject/version/hash values for the CommitmentRecord.
        """
        self.domain = domain_physics
        self.profile = subject_profile
        self.session_id = session_id or str(uuid.uuid4())
        self._policy_commitment = dict(policy_commitment or {})
        self._domain_lib_step_fn = domain_lib_step_fn

        # Domain-lib state: managed externally; the engine treats it as opaque.
        self.state = initial_state

        # Diagnostics for the most recently processed turn (read-only for callers)
        self.last_invariant_results: list[dict[str, Any]] = []
        self.last_domain_lib_decision: dict[str, Any] = {}

        # â”€â”€ Three collaborators â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self._resolver = ActorResolver(domain_physics)
        self._drafter = ContractDrafter(domain_physics, subject_profile, action_prompt_type_map)
        self._writer = SystemLogWriter(
            ledger_path,
            self.session_id,
            subject_profile,
            system_physics_hash=system_physics_hash,
            log_append_callback=log_append_callback,
        )

        # Write the session-open CommitmentRecord
        self._writer.write_commitment_record(domain_physics, self._policy_commitment)

    # â”€â”€ Backward-compat read-only properties â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @property
    def ledger_path(self) -> Path:
        return self._writer.ledger_path

    @property
    def log_records(self) -> list[dict[str, Any]]:
        """Read-only view of all System Log records written in this session."""
        return self._writer.log_records

    # â”€â”€ Backward-compat: standing-order state (tests read this directly) â”€â”€

    @property
    def _standing_order_attempts(self) -> dict[str, int]:
        """Live reference to the resolver's attempt counters (tests mutate via _resolve_action)."""
        return self._resolver._standing_order_attempts

    @property
    def last_standing_order_id(self) -> str | None:
        return self._resolver.last_standing_order_id

    @last_standing_order_id.setter
    def last_standing_order_id(self, value: str | None) -> None:
        self._resolver.last_standing_order_id = value

    @property
    def last_standing_order_attempt(self) -> int | None:
        return self._resolver.last_standing_order_attempt

    @last_standing_order_attempt.setter
    def last_standing_order_attempt(self, value: int | None) -> None:
        self._resolver.last_standing_order_attempt = value

    # â”€â”€ Public state-management API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def set_standing_order_attempts(self, attempts: dict[str, Any] | None) -> None:
        """Restore standing-order attempts from persisted session state."""
        self._resolver.set_attempts(attempts)

    def get_standing_order_attempts(self) -> dict[str, int]:
        """Expose standing-order attempts for session-state persistence."""
        return self._resolver.get_attempts()

    # â”€â”€ Backward-compat delegate methods (called by existing tests) â”€â”€â”€â”€â”€â”€â”€

    def _evaluate_invariants(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        return self._resolver.check_invariants(evidence)

    def _resolve_action(
        self,
        invariant_results: list[dict[str, Any]],
        domain_lib_decision: dict[str, Any],
    ) -> tuple[str | None, bool, str | None]:
        return self._resolver.resolve(invariant_results, domain_lib_decision)

    def _build_prompt_contract(
        self,
        task_spec: dict[str, Any],
        action: str | None,
        domain_lib_decision: dict[str, Any],
        standing_order_trigger: str | None,
    ) -> dict[str, Any]:
        return self._drafter.build(task_spec, action, domain_lib_decision, standing_order_trigger)

    def _write_commitment_record(self) -> None:
        self._writer.write_commitment_record(self.domain, self._policy_commitment)

    def _write_trace_event(
        self,
        task_spec: dict[str, Any],
        invariant_results: list[dict[str, Any]],
        domain_lib_decision: dict[str, Any],
        action: str | None,
        prompt_contract: dict[str, Any],
        provenance_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._writer.write_trace_event(
            task_spec,
            invariant_results,
            domain_lib_decision,
            action,
            prompt_contract,
            provenance_metadata,
            self._resolver.last_standing_order_id,
            self._resolver.last_standing_order_attempt,
        )

    def _write_escalation_record(
        self,
        task_spec: dict[str, Any],
        domain_lib_decision: dict[str, Any],
        trigger: str,
        provenance_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._writer.write_escalation_record(
            task_spec, domain_lib_decision, trigger, provenance_metadata,
            domain_physics=self.domain,
        )

    def _append_log_record(self, record: dict[str, Any]) -> None:
        self._writer._append_log_record(record)

    # â”€â”€ Private helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _step_domain_lib(
        self,
        task_spec: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Step the domain lib (if registered) and return its decision dict."""
        if self._domain_lib_step_fn is not None:
            self.state, decision = self._domain_lib_step_fn(
                self.state, task_spec, evidence
            )
            return decision
        return {}

    # â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def process_turn(
        self,
        task_spec: dict[str, Any],
        evidence: dict[str, Any],
        provenance_metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """
        Process one session turn through the full D.S.A. pipeline.

        Args:
            task_spec: Current task specification.
                       Required keys: task_id, nominal_difficulty, skills_required.
            evidence:  Structured evidence summary for this turn.
            provenance_metadata: Optional extra metadata attached to TraceEvent.

        Returns:
            (prompt_contract, resolved_action)
        """
        # 1. The Judge evaluates the evidence
        invariant_results = self._resolver.check_invariants(evidence)

        # 2. Domain Lib steps (if applicable)
        domain_lib_decision = self._step_domain_lib(task_spec, evidence)

        # Store diagnostics for the caller
        self.last_invariant_results = invariant_results
        self.last_domain_lib_decision = domain_lib_decision

        # 3. The Judge decides the action
        action, should_escalate, escalation_trigger = self._resolver.resolve(
            invariant_results, domain_lib_decision
        )

        # Operational logging — invariant failures become WARNING events.
        failed_invariants = [r for r in invariant_results if not r["passed"]]
        if failed_invariants:
            log_bus.emit(create_event(
                source="ppa_orchestrator",
                level=LogLevel.WARNING,
                category="invariant_check",
                message=f"{len(failed_invariants)} invariant(s) failed",
                data={
                    "session_id": self.session_id,
                    "task_id": task_spec.get("task_id", ""),
                    "failed_ids": [r["id"] for r in failed_invariants],
                },
            ))

        # Determine standing-order trigger label for the contract
        standing_order_trigger: str | None = None
        for result in invariant_results:
            if not result["passed"]:
                standing_order_trigger = result["standing_order_on_violation"]
                break
        if standing_order_trigger is None and action is not None:
            standing_order_trigger = action

        # 4. The Clerk drafts the contract
        prompt_contract = self._drafter.build(
            task_spec, action, domain_lib_decision, standing_order_trigger
        )

        trace_metadata = dict(provenance_metadata or {})
        trace_metadata["prompt_contract_hash"] = hash_payload(prompt_contract)

        # 5. The Scribe logs it
        self._writer.write_trace_event(
            task_spec,
            invariant_results,
            domain_lib_decision,
            action,
            prompt_contract,
            trace_metadata,
            self._resolver.last_standing_order_id,
            self._resolver.last_standing_order_attempt,
        )

        if should_escalate:
            self._writer.write_escalation_record(
                task_spec,
                domain_lib_decision,
                escalation_trigger or "domain_lib_escalation_event",
                trace_metadata,
                domain_physics=self.domain,
            )

        resolved_action = action if action is not None else "task_presentation"

        # Operational logging — successful turn processing.
        log_bus.emit(create_event(
            source="ppa_orchestrator",
            level=LogLevel.INFO,
            category="session_lifecycle",
            message=f"Turn processed — action={resolved_action}",
            data={
                "session_id": self.session_id,
                "task_id": task_spec.get("task_id", ""),
                "action": resolved_action,
            },
        ))

        return prompt_contract, resolved_action

    def append_provenance_trace(
        self,
        task_id: str,
        action: str,
        prompt_type: str,
        metadata: dict[str, Any],
    ) -> None:
        """Append an auxiliary TraceEvent carrying post-payload provenance hashes."""
        self._writer.append_provenance_trace(task_id, action, prompt_type, metadata)


    # â”€â”€ Kept for _append_log_record callers â”€â”€ (nothing to add here; method is above)
