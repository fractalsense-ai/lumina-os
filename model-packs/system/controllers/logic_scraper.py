"""
logic_scraper.py — Iterative LLM probing for novel synthesis discovery.

Runs a prompt N times through the LLM, feeding back prior responses to
force novelty on each iteration.  Novel synthesis detection runs per
iteration; flagged iterations (~20 % expected yield) produce proposals
for Domain Authority review.

Design: domain-agnostic system tool.  Zero domain-specific names.
Uses the existing SLM/LLM pipeline (``call_slm_fn``) for invocation.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from lumina.core.persona_builder import PersonaContext, build_system_prompt
from lumina.daemon.report import Proposal

log = logging.getLogger("lumina-logic-scraper")

# ── Default configuration ────────────────────────────────────

_DEFAULT_MAX_ITERATIONS = 100
_DEFAULT_FEEDBACK_MODE = "cumulative"
_DEFAULT_SLIDING_WINDOW_SIZE = 10
_DEFAULT_SYNTHESIS_YIELD_THRESHOLD = 0.1


# ── Result dataclass ─────────────────────────────────────────


@dataclass
class LogicScrapeResult:
    """Aggregate result of a logic scrape run."""

    scrape_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str = ""
    prompt_hash: str = ""
    iterations_run: int = 0
    total_flagged: int = 0
    yield_rate: float = 0.0
    flagged_items: list[dict[str, Any]] = field(default_factory=list)
    trace_verification: dict[str, Any] = field(default_factory=dict)
    proposals: list[Proposal] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scrape_id": self.scrape_id,
            "prompt": self.prompt,
            "prompt_hash": self.prompt_hash,
            "iterations_run": self.iterations_run,
            "total_flagged": self.total_flagged,
            "yield_rate": round(self.yield_rate, 4),
            "flagged_items": self.flagged_items,
            "trace_verification": self.trace_verification,
            "proposals": [p.to_dict() for p in self.proposals],
            "duration_seconds": round(self.duration_seconds, 2),
        }


# ── Prompt feedback helpers ──────────────────────────────────


def _summarise_response(response: str, max_chars: int = 300) -> str:
    """Compress a response to its key claims for feedback accumulation.

    Keeps the first *max_chars* characters as a pragmatic summary.
    A production implementation could use the SLM for abstractive
    summarisation — this deterministic version avoids extra LLM calls.
    """
    stripped = response.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[:max_chars] + "..."


def _build_augmented_prompt(
    original_prompt: str,
    prior_summaries: list[str],
    feedback_mode: str,
    sliding_window_size: int,
) -> str:
    """Construct the LLM prompt with feedback from prior iterations."""
    if not prior_summaries:
        return original_prompt

    if feedback_mode == "sliding_window":
        window = prior_summaries[-sliding_window_size:]
    else:  # cumulative
        window = prior_summaries

    feedback_block = "\n---\n".join(
        f"[Response {i + 1}] {s}" for i, s in enumerate(window)
    )
    return (
        f"{original_prompt}\n\n"
        f"--- Prior responses (do not repeat these ideas) ---\n"
        f"{feedback_block}\n"
        f"--- End prior responses ---\n\n"
        f"Provide a novel perspective that differs from the responses above."
    )


# ── Novel synthesis detection ────────────────────────────────


def _detect_novel_synthesis(
    response: str,
    invariants: list[dict[str, Any]],
    check_fn: Callable[[str, dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    """Check domain invariants for novel synthesis signals.

    Parameters
    ----------
    response : str
        The LLM response to check.
    invariants : list[dict]
        Domain physics invariants (only those with ``signal_type`` are
        relevant for novel synthesis detection).
    check_fn : callable, optional
        A function ``(response, invariant) -> bool`` that returns True
        when the invariant's check **fails** (i.e. the pattern is *not*
        recognized, indicating potential novelty).  If None, invariants
        with ``signal_type`` are automatically flagged (useful for
        testing and placeholder operation).

    Returns
    -------
    list[dict]
        One entry per flagged invariant with keys ``invariant_id`` and
        ``signal_type``.
    """
    flagged: list[dict[str, Any]] = []
    for inv in invariants:
        signal_type = inv.get("signal_type")
        if not signal_type:
            continue

        if check_fn is not None:
            is_novel = check_fn(response, inv)
        else:
            # Default: every invariant with a signal_type is flagged.
            # Real implementation would evaluate the check expression
            # against domain adapter output.
            is_novel = True

        if is_novel:
            flagged.append({
                "invariant_id": inv.get("id", "unknown"),
                "signal_type": signal_type,
            })
    return flagged


# ── Trace verification ───────────────────────────────────────


def _verify_traces(
    flagged_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Post-loop verification: deduplicate and check consistency.

    Groups flagged items by their summary text and removes near-exact
    duplicates.  Returns verification metadata.
    """
    seen_summaries: set[str] = set()
    unique: list[dict[str, Any]] = []
    duplicates_removed = 0

    for item in flagged_items:
        summary = item.get("summary", "")
        # Simple dedup: hash the summary
        digest = hashlib.sha256(summary.encode()).hexdigest()[:16]
        if digest in seen_summaries:
            duplicates_removed += 1
        else:
            seen_summaries.add(digest)
            unique.append(item)

    return {
        "total_before_dedup": len(flagged_items),
        "duplicates_removed": duplicates_removed,
        "unique_count": len(unique),
        "unique_items": unique,
        "consistency_check": "pass" if unique else "no_items",
    }


# ── Main Logic Scraper ───────────────────────────────────────


class LogicScraper:
    """Iterative LLM probing engine for novel synthesis discovery.

    Parameters
    ----------
    call_llm_fn : callable
        Function ``(system_prompt: str, user_prompt: str) -> str``
        for LLM invocation (routed via the SLM pipeline).
    domain_physics : dict
        Active domain physics document — used to extract invariants
        with ``signal_type`` for novel synthesis detection.
    config : dict, optional
        The ``logic_scraping`` config block from domain physics.
    check_fn : callable, optional
        Custom invariant check function for novel synthesis detection.
        See ``_detect_novel_synthesis`` for signature.
    """

    def __init__(
        self,
        call_llm_fn: Callable[..., str],
        domain_physics: dict[str, Any],
        config: dict[str, Any] | None = None,
        check_fn: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self._call_llm = call_llm_fn
        self._physics = domain_physics
        self._config = config or domain_physics.get("logic_scraping") or {}
        self._check_fn = check_fn

        self._invariants = [
            inv for inv in (domain_physics.get("invariants") or [])
            if inv.get("signal_type")
        ]

    @property
    def max_iterations(self) -> int:
        return int(self._config.get("max_iterations", _DEFAULT_MAX_ITERATIONS))

    @property
    def feedback_mode(self) -> str:
        return str(self._config.get("feedback_mode", _DEFAULT_FEEDBACK_MODE))

    @property
    def sliding_window_size(self) -> int:
        return int(self._config.get("sliding_window_size", _DEFAULT_SLIDING_WINDOW_SIZE))

    @property
    def synthesis_yield_threshold(self) -> float:
        return float(self._config.get("synthesis_yield_threshold", _DEFAULT_SYNTHESIS_YIELD_THRESHOLD))

    def scrape(
        self,
        prompt: str,
        iterations: int | None = None,
        domain_id: str = "",
        actor_id: str = "",
    ) -> LogicScrapeResult:
        """Run the iterative LLM probing loop.

        Parameters
        ----------
        prompt : str
            The question or scenario to probe.
        iterations : int, optional
            Override the configured max_iterations.
        domain_id : str
            Domain context for proposals.
        actor_id : str
            Actor triggering the scrape.

        Returns
        -------
        LogicScrapeResult
        """
        start = time.monotonic()
        n = min(iterations or self.max_iterations, self.max_iterations)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

        scrape_id = str(uuid.uuid4())
        prior_summaries: list[str] = []
        flagged_items: list[dict[str, Any]] = []

        system_prompt = build_system_prompt(PersonaContext.LOGIC_SCRAPER)

        for i in range(n):
            augmented = _build_augmented_prompt(
                prompt, prior_summaries,
                self.feedback_mode, self.sliding_window_size,
            )

            try:
                response = self._call_llm(system_prompt, augmented)
            except Exception as exc:
                log.warning("LLM call failed on iteration %d: %s", i + 1, exc)
                continue

            # Novel synthesis detection
            signals = _detect_novel_synthesis(
                response, self._invariants, self._check_fn,
            )
            if signals:
                summary = _summarise_response(response)
                flagged_items.append({
                    "iteration": i + 1,
                    "summary": summary,
                    "signals": signals,
                    "scrape_id": scrape_id,
                    "prompt_hash": prompt_hash,
                })

            # Accumulate feedback
            prior_summaries.append(_summarise_response(response))

        # Trace verification
        verification = _verify_traces(flagged_items)

        # Generate proposals from unique flagged items
        proposals: list[Proposal] = []
        for item in verification["unique_items"]:
            signal_types = ", ".join(s["signal_type"] for s in item.get("signals", []))
            proposals.append(Proposal(
                task="logic_scraping",
                domain_id=domain_id,
                proposal_type="novel_synthesis_candidate",
                summary=(
                    f"Logic scrape iteration {item['iteration']}: "
                    f"novel synthesis signal ({signal_types})"
                ),
                detail={
                    "iteration": item["iteration"],
                    "summary": item["summary"],
                    "signals": item["signals"],
                    "scrape_id": scrape_id,
                    "prompt_hash": prompt_hash,
                },
            ))

        duration = time.monotonic() - start
        yield_rate = len(flagged_items) / n if n > 0 else 0.0

        return LogicScrapeResult(
            scrape_id=scrape_id,
            prompt=prompt,
            prompt_hash=prompt_hash,
            iterations_run=n,
            total_flagged=len(flagged_items),
            yield_rate=yield_rate,
            flagged_items=flagged_items,
            trace_verification=verification,
            proposals=proposals,
            duration_seconds=duration,
        )
