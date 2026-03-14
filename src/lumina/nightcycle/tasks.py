"""
tasks.py — Night Cycle task implementations.

Each task function accepts a domain context dict and returns a TaskResult.
Tasks are designed to be domain-scoped — they operate on one domain at a time.
The scheduler calls each task for each eligible domain.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from lumina.nightcycle.report import Proposal, TaskResult

log = logging.getLogger("lumina-nightcycle")


# ── Task registry ────────────────────────────────────────────

_TASK_REGISTRY: dict[str, Callable[..., TaskResult]] = {}


def register_task(name: str) -> Callable:
    """Decorator to register a night-cycle task function."""
    def decorator(fn: Callable[..., TaskResult]) -> Callable[..., TaskResult]:
        _TASK_REGISTRY[name] = fn
        return fn
    return decorator


def get_task(name: str) -> Callable[..., TaskResult] | None:
    return _TASK_REGISTRY.get(name)


def list_tasks() -> list[str]:
    return list(_TASK_REGISTRY.keys())


# ── Task implementations ─────────────────────────────────────
# Each task is intentionally lightweight — it inspects domain state
# and generates Proposals for DA review rather than making direct changes.


@register_task("glossary_expansion")
def glossary_expansion(
    domain_id: str,
    domain_physics: dict[str, Any],
    persistence: Any = None,
    call_slm_fn: Callable | None = None,
) -> TaskResult:
    """Scan recent ingestions for terms not yet in the domain glossary."""
    start = time.monotonic()
    glossary = domain_physics.get("glossary") or []
    existing_terms = {entry.get("term", "").lower() for entry in glossary}

    proposals: list[Proposal] = []

    # Check ingestion records for new terms (simplified heuristic)
    if persistence is not None:
        try:
            records = persistence.query_ctl_records(domain_id=domain_id)
            for rec in records:
                if rec.get("record_type") != "IngestionRecord":
                    continue
                for interp in rec.get("interpretations") or []:
                    yaml_text = interp.get("yaml_content", "")
                    # Simple word extraction — real impl would use SLM
                    for word in yaml_text.split():
                        cleaned = word.strip(":-,.").lower()
                        if len(cleaned) > 3 and cleaned not in existing_terms:
                            existing_terms.add(cleaned)
                            proposals.append(Proposal(
                                task="glossary_expansion",
                                domain_id=domain_id,
                                proposal_type="glossary_add",
                                summary=f"New term candidate: {cleaned}",
                                detail={"term": cleaned, "source": "ingestion"},
                            ))
        except Exception as exc:
            log.warning("glossary_expansion scan failed: %s", exc)

    return TaskResult(
        task="glossary_expansion",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
    )


@register_task("glossary_pruning")
def glossary_pruning(
    domain_id: str,
    domain_physics: dict[str, Any],
    **_kw: Any,
) -> TaskResult:
    """Identify unused or redundant glossary terms."""
    start = time.monotonic()
    glossary = domain_physics.get("glossary") or []
    proposals: list[Proposal] = []

    # Flag terms without definitions or examples
    for entry in glossary:
        if not entry.get("definition"):
            proposals.append(Proposal(
                task="glossary_pruning",
                domain_id=domain_id,
                proposal_type="glossary_prune",
                summary=f"Term '{entry.get('term', '?')}' has no definition",
                detail={"term": entry.get("term"), "reason": "missing_definition"},
            ))

    return TaskResult(
        task="glossary_pruning",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
    )


@register_task("rejection_corpus_alignment")
def rejection_corpus_alignment(
    domain_id: str,
    domain_physics: dict[str, Any],
    **_kw: Any,
) -> TaskResult:
    """Validate rejection corpus entries are still aligned with current modules."""
    start = time.monotonic()
    rejection_corpus = domain_physics.get("rejection_corpus") or []
    proposals: list[Proposal] = []

    # Flag entries that reference modules not in current domain
    module_ids = {m.get("module_id") for m in (domain_physics.get("modules") or [])}
    for entry in rejection_corpus:
        ref_module = entry.get("module_id")
        if ref_module and ref_module not in module_ids:
            proposals.append(Proposal(
                task="rejection_corpus_alignment",
                domain_id=domain_id,
                proposal_type="rejection_stale",
                summary=f"Rejection entry references removed module '{ref_module}'",
                detail={"entry": entry, "reason": "module_removed"},
            ))

    return TaskResult(
        task="rejection_corpus_alignment",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
    )


@register_task("cross_module_consistency")
def cross_module_consistency(
    domain_id: str,
    domain_physics: dict[str, Any],
    **_kw: Any,
) -> TaskResult:
    """Check for conflicting prerequisites or duplicate coverage across modules."""
    start = time.monotonic()
    modules = domain_physics.get("modules") or []
    proposals: list[Proposal] = []

    # Check for prerequisite cycles (simplified)
    prereq_map: dict[str, list[str]] = {}
    for mod in modules:
        mid = mod.get("module_id", "")
        prereqs = mod.get("prerequisites") or []
        prereq_map[mid] = prereqs

    for mid, prereqs in prereq_map.items():
        for prereq in prereqs:
            if mid in prereq_map.get(prereq, []):
                proposals.append(Proposal(
                    task="cross_module_consistency",
                    domain_id=domain_id,
                    proposal_type="prerequisite_cycle",
                    summary=f"Prerequisite cycle: {mid} <-> {prereq}",
                    detail={"module_a": mid, "module_b": prereq},
                ))

    return TaskResult(
        task="cross_module_consistency",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
    )


@register_task("knowledge_graph_rebuild")
def knowledge_graph_rebuild(
    domain_id: str,
    domain_physics: dict[str, Any],
    **_kw: Any,
) -> TaskResult:
    """Reindex concepts and relationships from all modules."""
    start = time.monotonic()
    modules = domain_physics.get("modules") or []
    concepts: list[str] = []

    for mod in modules:
        for artifact in mod.get("artifacts") or []:
            concepts.append(artifact.get("name", ""))

    return TaskResult(
        task="knowledge_graph_rebuild",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        metadata={"concept_count": len(concepts), "module_count": len(modules)},
    )


@register_task("pacing_heuristic_recompute")
def pacing_heuristic_recompute(
    domain_id: str,
    domain_physics: dict[str, Any],
    **_kw: Any,
) -> TaskResult:
    """Recalculate pacing parameters based on accumulated session data."""
    start = time.monotonic()
    # Placeholder — full implementation would aggregate session metrics
    return TaskResult(
        task="pacing_heuristic_recompute",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        metadata={"note": "placeholder — needs session data aggregation"},
    )


@register_task("domain_physics_constraint_refresh")
def domain_physics_constraint_refresh(
    domain_id: str,
    domain_physics: dict[str, Any],
    **_kw: Any,
) -> TaskResult:
    """Validate all domain physics constraints still hold after new content."""
    start = time.monotonic()
    invariants = domain_physics.get("invariants") or []
    proposals: list[Proposal] = []

    for inv in invariants:
        # Simplified: check that referenced modules exist
        ref_modules = inv.get("applies_to") or []
        existing = {m.get("module_id") for m in (domain_physics.get("modules") or [])}
        for ref in ref_modules:
            if ref not in existing:
                proposals.append(Proposal(
                    task="domain_physics_constraint_refresh",
                    domain_id=domain_id,
                    proposal_type="invariant_orphan",
                    summary=f"Invariant '{inv.get('id', '?')}' references missing module '{ref}'",
                    detail={"invariant_id": inv.get("id"), "missing_module": ref},
                ))

    return TaskResult(
        task="domain_physics_constraint_refresh",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
    )


@register_task("slm_hint_generation")
def slm_hint_generation(
    domain_id: str,
    domain_physics: dict[str, Any],
    **_kw: Any,
) -> TaskResult:
    """Pre-generate SLM context hints for new content."""
    start = time.monotonic()
    # Placeholder — would call SLM to create context summaries
    return TaskResult(
        task="slm_hint_generation",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        metadata={"note": "placeholder — needs SLM integration"},
    )


@register_task("telemetry_summary_refresh")
def telemetry_summary_refresh(
    domain_id: str,
    domain_physics: dict[str, Any],
    **_kw: Any,
) -> TaskResult:
    """Rebuild summary metrics for the domain."""
    start = time.monotonic()
    return TaskResult(
        task="telemetry_summary_refresh",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        metadata={"note": "placeholder — needs telemetry store"},
    )
