---
version: 1.0.0
last_updated: 2026-03-20
---

# Logic Scraping

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-15

---

This document defines how Project Lumina uses iterative LLM probing to discover novel synthesis candidates.  Logic scraping extends the [Novel Synthesis Framework](novel-synthesis-framework.md) from passive detection (waiting for novel patterns to emerge during sessions) to active discovery (deliberately probing the LLM for ideas that do not match known patterns).

---

## A. What Is Logic Scraping?

**Logic scraping** is a domain-level tool that iterates a prompt through the LLM N times, feeding back prior responses to force the model into novel territory on each iteration.  Novel synthesis detection runs on every response; flagged items (~20% expected yield) are escalated to the Domain Authority for review via the existing two-key verification gate.

Example scenario:  A domain authority asks *"How can I help teach a bunch of kids who live in a trailer park algebra, they are in the 9th grade and struggle with simple concepts?"*  The system runs this prompt 100 times through the LLM, accumulating feedback so the model cannot repeat itself.  Approximately 20 of those responses contain approaches that do not match any known pattern in the domain physics — these are flagged as novel synthesis candidates and brought to the domain authority for review.

---

## B. Iterative LLM Probing with Feedback

The core loop works as follows:

```
for i in 1..N:
    augmented_prompt = original + "do not repeat these:" + prior_summaries
    response = call_llm(augmented_prompt)
    signals = detect_novel_synthesis(response, domain_invariants)
    if signals:
        flagged_items.append({iteration: i, summary, signals})
    prior_summaries.append(summarise(response))
```

### Feedback Accumulation

Two feedback modes are available:

| Mode | Behaviour | Use When |
|------|-----------|----------|
| `cumulative` (default) | All prior response summaries are included in the prompt | Iterations < 50; avoids repetition most aggressively |
| `sliding_window` | Only the last N summaries are included | Iterations > 50; prevents context overflow |

Each response is compressed to a summary (~300 characters) before feedback accumulation.  This prevents the prompt from growing unboundedly while preserving the key claims and methods from each iteration.

---

## C. Novel Synthesis Detection Per Iteration

On each iteration, the response is checked against domain invariants that have a `signal_type` field.  When an invariant's check evaluates to false (the response contains a pattern not recognized by existing rules), the novel synthesis signal fires.

This is the same detection mechanism used in real-time sessions — the difference is that logic scraping runs it in a tight loop against many iterations rather than waiting for a student interaction to trigger it.

---

## D. Logical Trace Verification

After all iterations complete, a post-loop verification pass runs across all flagged items:

1. **Deduplication**: Near-identical flagged responses (by summary hash) are collapsed.
2. **Consistency check**: Remaining unique items are verified for internal consistency.
3. **Yield rate**: `flagged / total_iterations` is computed.  A low yield rate (below the configured `synthesis_yield_threshold`) indicates the prompt may not be productive for novel discovery.

---

## E. Domain Authority Review Workflow

1. The logic scrape produces `Proposal` objects — one per unique flagged response.
2. Proposals appear in the governance dashboard under the night cycle review panel.
3. The domain authority reviews each proposal and approves or rejects it.
4. Approved proposals generate `novel_synthesis_verified` commitment records in the System Logs.
5. Rejected proposals generate `novel_synthesis_rejected` commitment records with `denial_rationale`.

The night cycle `logic_scrape_review` task surfaces any pending proposals during scheduled runs.

---

## F. Configuration

Logic scraping is configured in each domain's `domain-physics.yaml`:

```yaml
logic_scraping:
  enabled: true
  max_iterations: 100          # maximum iterations per scrape
  synthesis_yield_threshold: 0.1   # minimum useful yield rate (10%)
  feedback_mode: cumulative    # or sliding_window
  sliding_window_size: 10      # only used in sliding_window mode
```

When `logic_scraping` is omitted or `enabled: false`, the tool is unavailable for that domain.

---

## G. API Usage

### Submit a scrape

```
POST /api/admin/logic-scrape
Authorization: Bearer <domain_authority_token>
Content-Type: application/json

{
  "prompt": "How can I help teach algebra to 9th graders who struggle with basic concepts?",
  "iterations": 100,
  "domain_id": "education"
}
```

**Response** (immediate):
```json
{
  "scrape_id": "uuid",
  "status": "running"
}
```

### Poll results

```
GET /api/admin/logic-scrape/<scrape_id>
Authorization: Bearer <token>
```

**Response** (when complete):
```json
{
  "status": "completed",
  "scrape_id": "uuid",
  "prompt": "...",
  "prompt_hash": "sha256...",
  "iterations_run": 100,
  "total_flagged": 22,
  "yield_rate": 0.22,
  "flagged_items": [...],
  "trace_verification": {
    "duplicates_removed": 3,
    "unique_count": 19
  },
  "proposals": [...],
  "duration_seconds": 145.3
}
```

---

## H. Relationship to Novel Synthesis Framework

Logic scraping is an *active* extension of the [Novel Synthesis Framework](novel-synthesis-framework.md):

| Novel Synthesis (passive) | Logic Scraping (active) |
|---------------------------|-------------------------|
| Waits for novel patterns during live sessions | Deliberately probes the LLM for novel patterns |
| One response per session turn | N responses per scrape invocation |
| LLM flags + DA confirms (two-key) | LLM flags + DA confirms (same two-key) |
| TraceEvent: `novel_synthesis_flagged` | TraceEvent: `logic_scrape_flagged` |
| Triggered by student interaction | Triggered by domain authority on-demand |
| Real-time | Batch (asynchronous) |

The two-key verification gate is identical: the system flags, the domain authority confirms.  Logic scraping simply provides a structured way to generate more candidates for the gate.
