"""
tasks.py -- Daemon task implementations.

Each task function accepts a domain context dict and returns a TaskResult.
Tasks are designed to be domain-scoped — they operate on one domain at a time.
The daemon scheduler calls each task for each eligible domain.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from lumina.daemon.report import Proposal, TaskResult
from lumina.daemon.cross_domain import find_synthesis_candidates

log = logging.getLogger("lumina-daemon")


# ── Task registry ────────────────────────────────────────────

_TASK_REGISTRY: dict[str, Callable[..., TaskResult]] = {}
_CROSS_DOMAIN_TASK_REGISTRY: dict[str, Callable[..., TaskResult]] = {}


def register_task(name: str) -> Callable:
    """Decorator to register a daemon task function."""
    def decorator(fn: Callable[..., TaskResult]) -> Callable[..., TaskResult]:
        _TASK_REGISTRY[name] = fn
        return fn
    return decorator


def register_cross_domain_task(name: str) -> Callable:
    """Decorator to register a cross-domain daemon task.

    Cross-domain tasks receive ``domains`` (list of all opt-in domain dicts)
    instead of a single ``domain_id`` / ``domain_physics`` pair.
    """
    def decorator(fn: Callable[..., TaskResult]) -> Callable[..., TaskResult]:
        _CROSS_DOMAIN_TASK_REGISTRY[name] = fn
        return fn
    return decorator


def get_task(name: str) -> Callable[..., TaskResult] | None:
    return _TASK_REGISTRY.get(name)


def get_cross_domain_task(name: str) -> Callable[..., TaskResult] | None:
    return _CROSS_DOMAIN_TASK_REGISTRY.get(name)


def list_tasks() -> list[str]:
    return list(_TASK_REGISTRY.keys())


def list_cross_domain_tasks() -> list[str]:
    return list(_CROSS_DOMAIN_TASK_REGISTRY.keys())


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
            records = persistence.query_log_records(domain_id=domain_id)
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
    """Build the global knowledge index from all domain physics.

    This is the per-domain entry point called by the daemon batch scheduler.
    It feeds the domain_physics into the singleton KnowledgeIndex.  When
    called for multiple domains during a full daemon batch run, the scheduler
    accumulates all domain contexts and the final call triggers a full
    rebuild + persist.

    The *_kw* keyword bag may contain:
    - ``all_domain_contexts``: dict[str, dict] — when provided, triggers a
      full multi-domain rebuild instead of a single-domain partial update.
    - ``knowledge_index``: KnowledgeIndex — explicit index instance (for tests).
    - ``index_dir``: Path — persistence directory override.
    """
    from lumina.core.knowledge_index import KnowledgeIndex
    from pathlib import Path

    start = time.monotonic()

    # Use provided index or create a fresh one
    index: KnowledgeIndex = _kw.get("knowledge_index") or KnowledgeIndex()
    index_dir = _kw.get("index_dir") or Path(__file__).resolve().parents[2] / "data" / "knowledge-index"

    # Full rebuild when all_domain_contexts is supplied
    all_contexts = _kw.get("all_domain_contexts")
    if all_contexts:
        summary = index.build(all_contexts)
    else:
        # Single-domain partial: wrap the one domain context
        summary = index.build({domain_id: {"domain": domain_physics}})

    index.save(Path(index_dir))

    return TaskResult(
        task="knowledge_graph_rebuild",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        metadata=summary,
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
    call_slm_fn: Callable | None = None,
    **_kw: Any,
) -> TaskResult:
    """Pre-generate SLM context hints for each standing order + invariant pair.

    For each standing order in domain physics, the SLM is prompted (using the
    DAEMON_BATCH persona) to produce a concise domain-language summary of what
    is happening when that standing order fires.  The resulting hint is stored
    as a Proposal of type ``slm_hint`` for Domain Authority review.  This avoids
    per-session cold synthesis — the SLM works from static physics during the
    daemon batch and the approved hints are available inline at run-time.

    If no ``call_slm_fn`` is provided the task skips hint generation gracefully
    and records a warning rather than blocking the daemon batch.
    """
    import json as _json

    from lumina.core.persona_builder import PersonaContext, build_system_prompt

    start = time.monotonic()
    proposals: list[Proposal] = []

    if call_slm_fn is None:
        log.warning(
            "slm_hint_generation: no call_slm_fn provided for domain %s — skipping",
            domain_id,
        )
        return TaskResult(
            task="slm_hint_generation",
            domain_id=domain_id,
            success=True,
            duration_seconds=time.monotonic() - start,
            metadata={"skipped": True, "reason": "no call_slm_fn provided"},
        )

    standing_orders = domain_physics.get("standing_orders") or []
    invariants_by_id: dict[str, dict] = {
        inv.get("id", ""): inv
        for inv in (domain_physics.get("invariants") or [])
    }
    system_prompt = build_system_prompt(PersonaContext.DAEMON_BATCH)

    for so in standing_orders:
        so_id = so.get("id", "unknown")
        # Collect invariants that link to this standing order via
        # standing_order_on_violation.
        linked_invariants = [
            inv for inv in (domain_physics.get("invariants") or [])
            if inv.get("standing_order_on_violation") == so_id
        ]

        payload = {
            "task": "generate_standing_order_hint",
            "domain_id": domain_id,
            "standing_order": {
                "id": so_id,
                "action": so.get("action"),
                "description": so.get("description", ""),
                "trigger_condition": so.get("trigger_condition"),
                "max_attempts": so.get("max_attempts"),
                "escalation_on_exhaust": so.get("escalation_on_exhaust"),
            },
            "linked_invariants": [
                {
                    "id": inv.get("id"),
                    "description": inv.get("description", ""),
                    "severity": inv.get("severity"),
                    "check": inv.get("check"),
                }
                for inv in linked_invariants
            ],
            "instruction": (
                "Produce a concise domain-language summary (1–2 sentences) describing "
                "what is happening in the domain when this standing order fires. "
                "Respond in JSON: {\"hint\": \"...\"}  — no other keys."
            ),
        }

        try:
            raw = call_slm_fn(
                system=system_prompt,
                user=_json.dumps(payload, indent=2, ensure_ascii=False),
            )
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            parsed = _json.loads(text.strip())
            hint_text = parsed.get("hint", "").strip()
        except Exception as exc:
            log.warning(
                "slm_hint_generation: SLM call failed for standing order %s in %s: %s",
                so_id, domain_id, exc,
            )
            hint_text = ""

        if hint_text:
            proposals.append(Proposal(
                task="slm_hint_generation",
                domain_id=domain_id,
                proposal_type="slm_hint",
                summary=f"Hint for standing order '{so_id}': {hint_text[:120]}",
                detail={
                    "standing_order_id": so_id,
                    "hint": hint_text,
                    "linked_invariant_ids": [inv.get("id") for inv in linked_invariants],
                },
            ))

    return TaskResult(
        task="slm_hint_generation",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
        metadata={
            "standing_orders_processed": len(standing_orders),
            "hints_generated": len(proposals),
        },
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


# ── Cross-domain task implementations ────────────────────────
# Cross-domain tasks receive the full list of domains instead of
# iterating per-domain.  They use register_cross_domain_task().


@register_cross_domain_task("cross_domain_synthesis")
def cross_domain_synthesis_task(
    domains: list[dict[str, Any]],
    persistence: Any = None,
    **_kw: Any,
) -> TaskResult:
    """Analyse opt-in domain pairs for structural and invariant similarities.

    Two-pass algorithm:
      Pass 1 — Glossary structural comparison (term, alias, related_terms overlap)
      Pass 2 — Invariant structure comparison (severity, delegation, chaining patterns)

    Produces dual-approval proposals: both domain authorities must approve.
    """
    start = time.monotonic()
    proposals: list[Proposal] = []

    candidates = find_synthesis_candidates(domains)

    for candidate in candidates:
        if not candidate["is_candidate"]:
            continue

        a_id = candidate["domain_a_id"]
        b_id = candidate["domain_b_id"]

        detail: dict[str, Any] = {}
        summary_parts: list[str] = []

        glossary = candidate.get("glossary_result")
        if glossary and glossary.get("passes_threshold"):
            detail["glossary_overlap"] = {
                "shared_terms": glossary["shared_terms"],
                "shared_related": glossary["shared_related"],
                "score": glossary["score"],
            }
            summary_parts.append(
                f"glossary overlap ({len(glossary['shared_terms'])} shared terms, "
                f"score={glossary['score']})"
            )

        invariant = candidate.get("invariant_result")
        if invariant and invariant.get("score", 0) > 0:
            detail["invariant_structure"] = {
                "matched_pairs": invariant["matched_pairs"],
                "score": invariant["score"],
            }
            summary_parts.append(
                f"invariant structure match ({len(invariant['matched_pairs'])} pairs, "
                f"score={invariant['score']})"
            )

        if not summary_parts:
            continue

        proposals.append(Proposal(
            task="cross_domain_synthesis",
            domain_id=f"{a_id}+{b_id}",
            proposal_type="cross_domain_similarity",
            summary=f"Cross-domain similarity between {a_id} and {b_id}: "
                    + "; ".join(summary_parts),
            detail=detail,
            required_approvers=[a_id, b_id],
        ))

    return TaskResult(
        task="cross_domain_synthesis",
        domain_id="cross_domain",
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
        metadata={
            "pairs_analysed": len(candidates),
            "candidates_found": sum(1 for c in candidates if c["is_candidate"]),
        },
    )


# ── Logic scrape review task ─────────────────────────────────
# Surfaces pending logic scrape proposals during daemon batch.
# The scrape itself is triggered on-demand via the admin API.


@register_task("logic_scrape_review")
def logic_scrape_review(
    domain_id: str,
    domain_physics: dict[str, Any],
    persistence: Any = None,
    **_kw: Any,
) -> TaskResult:
    """Surface pending logic scrape proposals for Domain Authority review.

    Scans persistence for completed scrape results whose proposals
    have not yet been reviewed.  Does *not* run the scrape itself.
    """
    start = time.monotonic()
    proposals: list[Proposal] = []

    logic_cfg = domain_physics.get("logic_scraping") or {}
    if not logic_cfg.get("enabled", False):
        return TaskResult(
            task="logic_scrape_review",
            domain_id=domain_id,
            success=True,
            duration_seconds=time.monotonic() - start,
            metadata={"skipped": "logic_scraping not enabled"},
        )

    # Query persistence for pending scrape proposals
    if persistence is not None:
        try:
            records = persistence.query_log_records(domain_id=domain_id)
            for rec in records:
                if rec.get("record_type") != "TraceEvent":
                    continue
                if rec.get("event_type") != "logic_scrape_flagged":
                    continue
                meta = rec.get("metadata") or {}
                proposals.append(Proposal(
                    task="logic_scrape_review",
                    domain_id=domain_id,
                    proposal_type="novel_synthesis_candidate",
                    summary=(
                        f"Logic scrape finding (scrape {meta.get('scrape_id', '?')}, "
                        f"iteration {meta.get('iteration', '?')})"
                    ),
                    detail=meta,
                ))
        except Exception as exc:
            log.warning("logic_scrape_review scan failed: %s", exc)

    return TaskResult(
        task="logic_scrape_review",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
    )


# ── Context crawler & gated staging tasks ─────────────────────
# These tasks integrate with the File Staging Service (Phase 4)
# to produce outputs that go through DA review before persisting.


@register_task("context_crawler")
def context_crawler(
    domain_id: str,
    domain_physics: dict[str, Any],
    call_slm_fn: Callable | None = None,
    **_kw: Any,
) -> TaskResult:
    """Crawl domain modules and stage context hints for DA approval.

    For each module the SLM is prompted (using the DAEMON_BATCH persona) to
    extract concise, reusable context hints — e.g. glossary summaries,
    frequently-triggered invariants, common failure patterns.  Each hint is
    staged via ``StagingService.stage_file()`` with ``template_id="context-hint"``
    so the Domain Authority can review before it becomes available at runtime.

    If no ``call_slm_fn`` is provided the task gracefully skips generation.
    """
    import json as _json

    start = time.monotonic()
    proposals: list[Proposal] = []

    modules = domain_physics.get("modules") or []
    invariants = domain_physics.get("invariants") or []
    glossary = domain_physics.get("glossary") or []

    if not modules:
        return TaskResult(
            task="context_crawler",
            domain_id=domain_id,
            success=True,
            duration_seconds=time.monotonic() - start,
            metadata={"skipped": True, "reason": "no modules in domain"},
        )

    if call_slm_fn is None:
        log.warning(
            "context_crawler: no call_slm_fn provided for domain %s — skipping",
            domain_id,
        )
        return TaskResult(
            task="context_crawler",
            domain_id=domain_id,
            success=True,
            duration_seconds=time.monotonic() - start,
            metadata={"skipped": True, "reason": "no call_slm_fn provided"},
        )

    from lumina.core.persona_builder import PersonaContext, build_system_prompt

    system_prompt = build_system_prompt(PersonaContext.DAEMON_BATCH)

    for mod in modules:
        module_id = mod.get("module_id", "unknown")

        # Gather invariants linked to this module
        linked_invariants = [
            inv for inv in invariants
            if module_id in (inv.get("applies_to") or [])
        ]

        payload = {
            "task": "generate_context_hints",
            "domain_id": domain_id,
            "module_id": module_id,
            "module_name": mod.get("name", module_id),
            "artifacts": [a.get("name", "") for a in (mod.get("artifacts") or [])],
            "linked_invariant_ids": [inv.get("id") for inv in linked_invariants],
            "glossary_term_count": len(glossary),
            "instruction": (
                "Produce 1–3 concise context hints for this module. "
                "Each hint should capture a key concept, common pitfall, "
                "or important relationship. Respond in JSON: "
                '[{"hint_id": "...", "content": "..."}]'
            ),
        }

        try:
            raw = call_slm_fn(
                system=system_prompt,
                user=_json.dumps(payload, indent=2, ensure_ascii=False),
            )
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            hints = _json.loads(text.strip())
            if not isinstance(hints, list):
                hints = [hints]
        except Exception as exc:
            log.warning(
                "context_crawler: SLM call failed for module %s in %s: %s",
                module_id, domain_id, exc,
            )
            continue

        for hint in hints:
            hint_id = hint.get("hint_id", f"{module_id}-hint-{len(proposals)}")
            content = hint.get("content", "").strip()
            if not content:
                continue

            proposals.append(Proposal(
                task="context_crawler",
                domain_id=domain_id,
                proposal_type="context_hint",
                summary=f"Context hint for module '{module_id}': {content[:120]}",
                detail={
                    "hint_id": hint_id,
                    "module_id": module_id,
                    "domain_id": domain_id,
                    "content": content,
                },
            ))

    return TaskResult(
        task="context_crawler",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
        metadata={
            "modules_processed": len(modules),
            "hints_generated": len(proposals),
        },
    )


@register_task("gated_staging")
def gated_staging(
    domain_id: str,
    domain_physics: dict[str, Any],
    call_slm_fn: Callable | None = None,
    **_kw: Any,
) -> TaskResult:
    """Draft glossary updates and data-stream sorts, staging all for DA approval.

    This task never auto-updates domain content.  All outputs pass through
    the StagingService review queue.  The SLM analyses the current glossary
    for gaps, inconsistencies, and ordering issues, then produces draft
    proposals that are staged for Domain Authority review.

    If no ``call_slm_fn`` is provided the task falls back to heuristic
    analysis of the existing glossary (detecting missing definitions,
    duplicate terms, and alphabetical ordering issues).
    """
    import json as _json

    start = time.monotonic()
    proposals: list[Proposal] = []

    glossary = domain_physics.get("glossary") or []
    modules = domain_physics.get("modules") or []

    # ── Heuristic pass (always runs) ──────────────────────────
    # Flag terms that could benefit from enrichment.
    seen_terms: dict[str, int] = {}
    for idx, entry in enumerate(glossary):
        term = (entry.get("term") or "").strip().lower()
        if not term:
            continue

        # Duplicate detection
        if term in seen_terms:
            proposals.append(Proposal(
                task="gated_staging",
                domain_id=domain_id,
                proposal_type="glossary_duplicate",
                summary=f"Duplicate glossary term: '{term}' (indices {seen_terms[term]}, {idx})",
                detail={"term": term, "indices": [seen_terms[term], idx]},
            ))
        seen_terms[term] = idx

        # Missing related_terms
        if not entry.get("related_terms"):
            proposals.append(Proposal(
                task="gated_staging",
                domain_id=domain_id,
                proposal_type="glossary_enrich",
                summary=f"Glossary term '{term}' has no related_terms",
                detail={"term": term, "reason": "missing_related_terms"},
            ))

    # ── SLM-enhanced pass (when available) ────────────────────
    if call_slm_fn is not None and modules:
        from lumina.core.persona_builder import PersonaContext, build_system_prompt

        system_prompt = build_system_prompt(PersonaContext.DAEMON_BATCH)

        module_names = [m.get("name", m.get("module_id", "?")) for m in modules]
        existing = [e.get("term", "") for e in glossary]

        payload = {
            "task": "draft_glossary_updates",
            "domain_id": domain_id,
            "existing_terms": existing[:50],  # cap for prompt size
            "module_names": module_names,
            "instruction": (
                "Identify 1–5 glossary terms that are missing from the current "
                "glossary but likely needed given the module names. For each term "
                "produce a draft entry. Respond in JSON: "
                '[{"term": "...", "definition": "...", "related_terms": [...]}]'
            ),
        }

        try:
            raw = call_slm_fn(
                system=system_prompt,
                user=_json.dumps(payload, indent=2, ensure_ascii=False),
            )
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            drafts = _json.loads(text.strip())
            if not isinstance(drafts, list):
                drafts = [drafts]
        except Exception as exc:
            log.warning(
                "gated_staging: SLM call failed for domain %s: %s",
                domain_id, exc,
            )
            drafts = []

        for draft in drafts:
            term = (draft.get("term") or "").strip()
            if not term or term.lower() in seen_terms:
                continue
            proposals.append(Proposal(
                task="gated_staging",
                domain_id=domain_id,
                proposal_type="glossary_draft",
                summary=f"Draft glossary entry: '{term}'",
                detail=draft,
            ))

    return TaskResult(
        task="gated_staging",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
        metadata={
            "glossary_size": len(glossary),
            "proposals_generated": len(proposals),
        },
    )


# ── Retrieval indexing task ──────────────────────────────────


@register_cross_domain_task("housekeeper_full_reindex")
def housekeeper_full_reindex(
    domains: list[dict[str, Any]],
    **_kw: Any,
) -> TaskResult:
    """Re-embed all docs into per-domain MiniLM vector stores.

    Walks every domain pack and the global ``docs/`` trees,
    rebuilding each domain's ``.npz`` store separately.  Falls back to
    the legacy single-store ``full_reindex`` when per-domain discovery
    finds nothing (preserving backward compat).

    Gracefully skips if ``sentence-transformers`` is not installed.
    """
    start = time.monotonic()

    try:
        from lumina.retrieval.housekeeper import (  # noqa: F811
            make_housekeeper,
            make_registry,
            rebuild_all_domain_indexes,
        )
    except ImportError as exc:
        log.info("housekeeper_full_reindex skipped: %s", exc)
        return TaskResult(
            task="housekeeper_full_reindex",
            domain_id="system",
            success=True,
            duration_seconds=time.monotonic() - start,
            metadata={"skipped": True, "reason": str(exc)},
        )

    try:
        registry = make_registry()
        summary = rebuild_all_domain_indexes(registry)
        success = True
    except ImportError as exc:
        # sentence-transformers not installed — skip gracefully
        log.info("housekeeper_full_reindex skipped (missing dep): %s", exc)
        summary = {"skipped": True, "reason": str(exc)}
        success = True
    except Exception as exc:
        log.warning("housekeeper_full_reindex failed: %s", exc)
        summary = {"error": str(exc)}
        success = False

    return TaskResult(
        task="housekeeper_full_reindex",
        domain_id="system",
        success=success,
        duration_seconds=time.monotonic() - start,
        metadata=summary,
    )


@register_task("rebuild_domain_vectors")
def rebuild_domain_vectors(
    domain_id: str = "default",
    domain_physics: dict[str, Any] | None = None,
    **_kw: Any,
) -> TaskResult:
    """Rebuild the vector index for a single domain pack.

    Called per-domain by the daemon task adapter when a Group Library or
    other domain content changes.
    """
    start = time.monotonic()

    try:
        from lumina.retrieval.housekeeper import make_registry, rebuild_domain_index  # noqa: F811
    except ImportError as exc:
        log.info("rebuild_domain_vectors(%s) skipped: %s", domain_id, exc)
        return TaskResult(
            task="rebuild_domain_vectors",
            domain_id=domain_id,
            success=True,
            duration_seconds=time.monotonic() - start,
            metadata={"skipped": True, "reason": str(exc)},
        )

    try:
        registry = make_registry()
        summary = rebuild_domain_index(domain_id, registry)
        success = True
    except ImportError as exc:
        log.info("rebuild_domain_vectors(%s) skipped (missing dep): %s", domain_id, exc)
        summary = {"skipped": True, "reason": str(exc)}
        success = True
    except Exception as exc:
        log.warning("rebuild_domain_vectors(%s) failed: %s", domain_id, exc)
        summary = {"error": str(exc)}
        success = False

    return TaskResult(
        task="rebuild_domain_vectors",
        domain_id=domain_id,
        success=success,
        duration_seconds=time.monotonic() - start,
        metadata=summary,
    )


# ── Phase G: spectral chronic-drift analysis ─────────────────


def _extract_sva_value(record: dict[str, Any], axis: str) -> float | None:
    """Defensively pull a single SVA axis value out of a TraceEvent record.

    Trace events have evolved over time; SVA can live in several places.
    We probe the most common locations in priority order rather than coupling
    the daemon to one exact wire-format. Returns None when no usable value
    found (caller skips that record).
    """
    candidates = (
        record.get("sva"),
        (record.get("metadata") or {}).get("sva"),
        (record.get("metadata") or {}).get("sva_direct"),
        (record.get("metadata") or {}).get("evidence", {}).get("sva_direct")
            if isinstance((record.get("metadata") or {}).get("evidence"), dict) else None,
        (record.get("decision_rationale") or {}).get("sva"),
    )
    for c in candidates:
        if isinstance(c, dict) and axis in c:
            try:
                return float(c[axis])
            except (TypeError, ValueError):
                continue
    return None


def _iter_actor_profiles(
    persistence: Any,
    domain_key: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Yield (user_id, profile_dict) for every profile stored under domain_key.

    Uses the standard list_users + list_profiles pair available on every
    persistence backend. Defensive: any backend missing those methods just
    returns an empty list (the task then no-ops cleanly).
    """
    out: list[tuple[str, dict[str, Any]]] = []
    if persistence is None:
        return out
    list_users = getattr(persistence, "list_users", None)
    list_profiles = getattr(persistence, "list_profiles", None)
    load_profile = getattr(persistence, "load_profile", None)
    if not (list_users and list_profiles and load_profile):
        return out
    try:
        users = list_users() or []
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("rhythm_fft_analysis: list_users failed: %s", exc)
        return out
    for u in users:
        uid = u.get("user_id") if isinstance(u, dict) else None
        if not uid:
            continue
        try:
            domain_keys = list_profiles(uid) or []
        except Exception:
            continue
        if domain_key not in domain_keys:
            continue
        try:
            profile = load_profile(uid, domain_key)
        except Exception:
            continue
        if profile:
            out.append((uid, profile))
    return out


# ── Spectral advisory helpers (Phase G.5) ────────────────────
#
# When ``rhythm_fft_analysis`` emits a chronic_spectral_drift Proposal it
# also writes a small advisory entry to the actor's profile so the journal
# session-start surface can render a soft banner.  Advisories carry their
# own TTL (24h) so the UI never has to call back to clear them.

_ADVISORY_TTL_SECONDS = 24 * 3600

# Keyed by (axis, band, direction).  "*" matches any direction.
_ADVISORY_MESSAGES: dict[tuple[str, str, str], str] = {
    ("valence", "dc_drift", "negative"):
        "Your overall mood has been drifting downward over the past few weeks.",
    ("valence", "dc_drift", "positive"):
        "Your overall mood has been trending upward recently.",
    ("valence", "circaseptan", "*"):
        "A weekly mood pattern has shifted noticeably.",
    ("valence", "ultradian", "*"):
        "Multi-day mood swings have become more pronounced.",
    ("arousal", "dc_drift", "positive"):
        "Your baseline arousal has been creeping upward over the past few weeks.",
    ("arousal", "dc_drift", "negative"):
        "Your baseline arousal has been settling lower over the past few weeks.",
    ("arousal", "circaseptan", "*"):
        "A weekly arousal pattern has shifted noticeably.",
    ("arousal", "ultradian", "*"):
        "Multi-day arousal swings have become more pronounced.",
    ("salience", "dc_drift", "*"):
        "How emotionally significant things feel has been drifting recently.",
    ("salience", "circaseptan", "*"):
        "A weekly salience pattern has shifted noticeably.",
    ("salience", "ultradian", "*"):
        "Multi-day salience swings have become more pronounced.",
}


def _advisory_message(axis: str, band: str, direction: str) -> str:
    """Look up a human-readable message for an advisory, with fallbacks."""
    key = (axis, band, direction)
    if key in _ADVISORY_MESSAGES:
        return _ADVISORY_MESSAGES[key]
    wildcard = (axis, band, "*")
    if wildcard in _ADVISORY_MESSAGES:
        return _ADVISORY_MESSAGES[wildcard]
    return f"A chronic {band} pattern has shifted on {axis}."


def _upsert_spectral_advisory(
    advisories: list[dict[str, Any]],
    *,
    axis: str,
    band: str,
    finding: dict[str, Any],
    now_utc: datetime | None = None,
    ttl_seconds: int = _ADVISORY_TTL_SECONDS,
) -> list[dict[str, Any]]:
    """Insert/replace an advisory keyed by (axis, band).

    Returns a new list (does not mutate input). Newer entries evict older
    entries for the same (axis, band) tuple. Expired entries are pruned.
    """
    now = now_utc or datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    direction = str(finding.get("direction", "neutral"))
    new_entry = {
        "advisory_id": str(uuid.uuid4()),
        "axis": axis,
        "band": band,
        "direction": direction,
        "z_score": float(finding.get("z_score", 0.0)),
        "message": _advisory_message(axis, band, direction),
        "created_utc": now.isoformat(),
        "expires_utc": expires.isoformat(),
    }
    out: list[dict[str, Any]] = []
    for adv in advisories or []:
        if not isinstance(adv, dict):
            continue
        # Drop the entry we are replacing.
        if adv.get("axis") == axis and adv.get("band") == band:
            continue
        # Drop already-expired entries.
        exp = adv.get("expires_utc")
        if isinstance(exp, str):
            try:
                if datetime.fromisoformat(exp) <= now:
                    continue
            except ValueError:
                continue
        out.append(adv)
    out.append(new_entry)
    return out


@register_task("rhythm_fft_analysis")
def rhythm_fft_analysis(
    domain_id: str,
    domain_physics: dict[str, Any],
    persistence: Any = None,
    call_slm_fn: Callable | None = None,
    *,
    profile_domain_key: str | None = None,
) -> TaskResult:
    """Run an FFT spectral chronic-drift scan for every actor in this domain.

    Phase A-F catch acute affect events on a per-turn timescale (envelope
    z-score) and an acute-rhythm timescale (run-length vs. crossing rate).
    Phase G fills the chronic gap: a slow weeks-long slide that stays inside
    the per-turn envelope and never produces a sustained run because the
    EWMA crawls along with it.

    For each actor:
      1. Pull recent TraceEvents and project a per-axis daily mean series
         spanning ``window_days`` (default 30).
      2. Compute a spectral signature (DC drift + circaseptan + ultradian
         + noise floor bands) via :mod:`lumina.daemon.rhythm_fft`.
      3. Fold today's signature into the actor's persisted EWMA spectral
         history.
      4. If the history is mature, compare today's signature against it.
         Each band whose z-score exceeds ``k_spectral`` becomes a Proposal
         of type ``chronic_spectral_drift`` for DA review. ``dc_drift``
         is asymmetric — only the harmful direction triggers (so recovery
         from a slump doesn't false-fire).
      5. Persist the updated history back onto the actor profile.

    The task respects ``TaskPreempted`` cooperatively per-actor — if the
    daemon scheduler signals preemption between actors we stop cleanly.
    """
    start = time.monotonic()
    proposals: list[Proposal] = []
    summary: dict[str, Any] = {
        "profiles_analyzed": 0,
        "profiles_skipped": 0,
        "axes_run": [],
    }

    # Lazy imports keep this task's failure modes isolated from the rest
    # of the registry (numpy/import errors don't poison glossary tasks).
    try:
        from lumina.daemon.rhythm_fft import (
            check_spectral_drift,
            compute_spectral_signature,
            resample_to_daily,
            update_spectral_history,
        )
    except ImportError as exc:
        return TaskResult(
            task="rhythm_fft_analysis",
            domain_id=domain_id,
            success=False,
            duration_seconds=time.monotonic() - start,
            error=f"rhythm_fft module unavailable: {exc}",
        )

    cfg = (
        domain_physics.get("spectral_drift_thresholds")
        or (domain_physics.get("domain_step_params") or {}).get("spectral_drift_thresholds")
        or {}
    )
    window_days = int(cfg.get("window_days", 30))
    k_spectral = float(cfg.get("k_spectral", 2.5))
    min_samples = int(cfg.get("min_samples_for_drift", 5))
    alpha = float(cfg.get("alpha", 0.1))
    axes = list(cfg.get("axes") or ["valence"])
    summary["axes_run"] = axes

    # The profile key used to store the AffectBaseline on disk is usually the
    # domain id itself for single-module domains; callers can override.
    domain_key = profile_domain_key or domain_id

    actor_profiles = _iter_actor_profiles(persistence, domain_key)
    if not actor_profiles:
        return TaskResult(
            task="rhythm_fft_analysis",
            domain_id=domain_id,
            success=True,
            duration_seconds=time.monotonic() - start,
            metadata={**summary, "no_profiles": True},
        )

    # Pull all recent records once and bucket by actor — much cheaper than
    # one query_log_records call per actor for a large user base.
    try:
        all_records = persistence.query_log_records(
            record_type="TraceEvent",
            domain_id=domain_id,
            limit=10000,
        )
    except Exception as exc:
        log.warning("rhythm_fft_analysis: query_log_records failed: %s", exc)
        all_records = []

    by_actor: dict[str, list[dict[str, Any]]] = {}
    for r in all_records:
        aid = r.get("actor_id")
        if aid:
            by_actor.setdefault(aid, []).append(r)

    save_profile = getattr(persistence, "save_profile", None)

    # Cooperative preemption: if the daemon's PreemptionToken is being
    # used elsewhere in this run, importing TaskPreempted lets the task
    # honor a stop signal between actors. Failure to import is fine.
    try:
        from lumina.daemon.preemption import TaskPreempted  # type: ignore
    except ImportError:  # pragma: no cover
        class TaskPreempted(Exception):  # type: ignore
            pass

    for user_id, profile in actor_profiles:
        try:
            learning_state = profile.get("learning_state") or {}
            baseline_dict = learning_state.get("global_affect_baseline") or {}
            spectral_history = dict(baseline_dict.get("spectral_history") or {})
            advisories = list(learning_state.get("spectral_advisories") or [])

            actor_records = by_actor.get(user_id, [])
            if not actor_records:
                summary["profiles_skipped"] += 1
                continue

            updated_for_actor = False
            for axis in axes:
                timestamps: list[str] = []
                values: list[float] = []
                for rec in actor_records:
                    v = _extract_sva_value(rec, axis)
                    if v is None:
                        continue
                    ts = rec.get("timestamp_utc")
                    if not ts:
                        continue
                    timestamps.append(ts)
                    values.append(v)

                series, n_real = resample_to_daily(
                    timestamps, values, window_days=window_days,
                )
                if len(series) == 0 or n_real < max(min_samples, 5):
                    continue

                today_sig = compute_spectral_signature(series)
                if not today_sig:
                    continue

                # Per-axis history is namespaced under the axis name so
                # adding more axes later doesn't collide.
                axis_hist = spectral_history.get(axis) or {}
                findings = check_spectral_drift(
                    axis_hist, today_sig,
                    k_spectral=k_spectral,
                    min_samples=min_samples,
                )
                axis_hist_new = update_spectral_history(
                    axis_hist, today_sig, alpha=alpha,
                )
                spectral_history[axis] = axis_hist_new
                updated_for_actor = True

                for f in findings:
                    proposals.append(Proposal(
                        task="rhythm_fft_analysis",
                        domain_id=domain_id,
                        proposal_type="chronic_spectral_drift",
                        summary=(
                            f"Chronic {f['band']} drift on {axis} for {user_id} "
                            f"(z={f['z_score']}, dir={f['direction']})"
                        ),
                        detail={
                            "user_id": user_id,
                            "axis": axis,
                            "band": f["band"],
                            "z_score": f["z_score"],
                            "today_value": f["today_value"],
                            "ewma_value": f["ewma_value"],
                            "direction": f["direction"],
                            "window_days": window_days,
                            "n_real_samples": n_real,
                        },
                    ))
                    # Mirror the proposal into a profile-side advisory so
                    # the journal session-start surface can render it.
                    advisories = _upsert_spectral_advisory(
                        advisories,
                        axis=axis,
                        band=f["band"],
                        finding=f,
                    )

            if updated_for_actor and save_profile is not None:
                # Round-trip back through learning_state to preserve siblings.
                baseline_dict["spectral_history"] = spectral_history
                learning_state["global_affect_baseline"] = baseline_dict
                learning_state["spectral_advisories"] = advisories
                profile["learning_state"] = learning_state
                try:
                    save_profile(user_id, domain_key, profile)
                except Exception as exc:
                    log.warning(
                        "rhythm_fft_analysis: save_profile(%s) failed: %s",
                        user_id, exc,
                    )

            summary["profiles_analyzed"] += 1
        except TaskPreempted:
            log.info("rhythm_fft_analysis preempted at actor %s", user_id)
            break
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "rhythm_fft_analysis(%s/%s) failed: %s",
                domain_id, user_id, exc,
            )
            summary["profiles_skipped"] += 1

    return TaskResult(
        task="rhythm_fft_analysis",
        domain_id=domain_id,
        success=True,
        duration_seconds=time.monotonic() - start,
        proposals=proposals,
        metadata=summary,
    )

