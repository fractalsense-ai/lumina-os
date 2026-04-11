"""
tasks.py -- Daemon task implementations.

Each task function accepts a domain context dict and returns a TaskResult.
Tasks are designed to be domain-scoped — they operate on one domain at a time.
The daemon scheduler calls each task for each eligible domain.
"""

from __future__ import annotations

import logging
import time
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
