---
version: 1.0.0
last_updated: 2026-03-28
---

# Concept — Compressed State Pattern

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-28  

---

## NAME

compressed-state-pattern — the design philosophy of passing deterministically-compressed historical state, rather than raw data, into SLM and LLM context.

## SYNOPSIS

Lumina deliberately does not give language models raw data. Every piece of context that reaches a model has been compressed by deterministic code into a structured summary that encodes not just a current value but its *trajectory* — where things came from and where they are headed. This removes a class of ambiguity that forces models to fabricate direction (hallucination), shrinks the input surface available to adversarial manipulation (prompt injection), and tends to produce more novel and appropriate outcomes because the model reasons over a meaningful curve rather than an isolated point.

---

## THE PATTERN

**Compressed state** means: take a raw, historically-ordered stream of data, push it through deterministic math, and output a compact summary that is authoritative about the present *and* its direction.

The key distinction from simply "providing context":

| Providing context | Compressed state |
|---|---|
| Include recent data so the model has something to work with | Compute a conclusion about that data and give the model the conclusion |
| Direction is inferred by the model | Direction is computed by code and stated as fact |
| Model must guess at trend from the data points provided | Trajectory is a field: `"rising"`, `"falling"`, `"spiking"` |
| Model may hallucinate a direction that is not present | Model can only reason over the authoritative direction |

The model receives *facts about state*, not raw material to interpret. This is intentional. The model's probabilistic nature is a strength when generating language; it is a liability when estimating trends from numbers. Deterministic code handles the estimation; the model handles the language.

---

## WHY TRAJECTORY MATTERS

A point-in-time reading answers "what is the value now?" A trajectory answers "where is this going?" Both are needed for useful reasoning.

Consider load score: a reading of `0.73` is ambiguous. Is the system recovering from a spike (trending down) or approaching saturation (trending up)? The appropriate response in each case is opposite. A model that sees `0.73` and no trajectory context is forced to guess, or give a hedged answer that treats both scenarios as equally likely.

Add `load_trajectory: "cliff_drop"` and the ambiguity is eliminated without the model doing any additional inference.

The same principle applies across all layers where Lumina uses compressed state:

- **A student's affect** — not just `frustration_score: 0.8` but the accumulated trend across the session (rising, plateau, sudden spike).
- **System load** — not just the current sample but the EWMA curve: is this a sustained rise or a transient blip?
- **Domain physics knowledge** — not a raw embedding search but the SLM's concluded interpretation: which invariants are relevant, which glossary terms apply, what the signal's domain meaning is.

---

## WHERE IT APPEARS IN LUMINA

Four concrete implementations, ordered by scope:

### 1. Telemetry Sliding Window

**The clearest example of the pattern.** The `TelemetryWindow` in `load_estimator.py` maintains a bounded deque of `LoadSnapshot` objects and computes a deterministic curve summary.

**Input:** raw hardware probe readings — event-loop latency (ms), in-flight HTTP requests, GPU VRAM %

**Processing (deterministic, no model):**
- EWMA with α = 0.3 for smooth curve tracking
- Trajectory classification: `stable`, `rising`, `falling`, `spiking`, `cliff_drop`
- Curve shape classification: `linear`, `exponential`, `plateau`
- Delta percentage from oldest to newest sample
- Peak, trough, baseline (window average)

**Output: dual-format compression**
```python
TelemetrySummary(
    json_summary={                    # → injected into LLM prompt as system_telemetry
        "load_trajectory": "rising",
        "load_delta_pct": 34.2,
        "curve": "exponential",
        "baseline": 0.41,
        "current": 0.68,
        "peak": 0.71,
        "trough": 0.29,
        "ewma": 0.63,
        "samples": 20,
    },
    numeric_vector=[0.68, 34.2, 0.41, 0.71, 0.29, 1.0],  # → threshold checks, no LLM
)
```

The `json_summary` travels into the LLM prompt payload as `system_telemetry`. The `numeric_vector` is used by the black-box trigger system and resource monitor daemon for threshold comparisons — operations where involving the LLM would be unnecessary overhead.

The LLM sees the curve conclusion. It never sees the 20 raw samples.

See [`telemetry-and-blackbox(7)`](telemetry-and-blackbox.md) for full architectural detail.

### 2. Entity Profile (Compressed Session History)

The entity profile is not a transcript. It is a compressed state of what the entity has done and where they currently stand. After each session, the orchestrator discards raw turn data and writes only the compressed state forward.

```yaml
entity_state:
  affect: recovered          # not raw sentiment scores — a concluded affect label
  mastery:                   # per-skill mastery estimates from evidence accumulation
    linear_equations: 0.74
    substitution_method: 0.81
  challenge_band:            # the range of problems that will keep ZPD engagement
    min: 0.55
    max: 0.70
  challenge: 0.62            # current challenge level within the band
  uncertainty: 0.38          # estimated uncertainty about current mastery
```

The model never reads raw session history. It reads a summary of state that was computed by the domain's evidence engine. The advantage is identical — the model reasons over a concluded state, not over a pile of raw data from which it must conclude state itself.

### 3. SLM Context Compression (Layer 2½)

The SLM layer sits between domain adapter A and the global base prompt. Its role is to receive the normalized input signal and produce a compressed interpretation of it in terms of the live domain physics.

Where the raw input might be `"I think x = 4"`, the SLM context adds:
```python
_slm_context = {
    "matched_invariants": ["solution_verifies", "standard_method_preferred"],
    "glossary_terms": ["substitution", "linear equation"],
    "context_summary": "Student claims a solution value. Algebra L1 invariants apply.",
    "suggested_evidence_fields": ["substitution_check", "method_recognized"],
}
```

The LLM does not receive the raw signal and the full physics file and a request to figure out what is relevant. It receives the SLM's concluded answer to that question. This compresses domain-physics knowledge — potentially a large and complex file — down to the specific invariants and terms that apply to this particular turn.

See [`slm-compute-distribution(7)`](slm-compute-distribution.md) for detail on when the SLM layer is active.

### 4. The Prompt Packet as a Compression Stack

The entire prompt packet assembly pipeline — described in [`prompt-packet-assembly(7)`](prompt-packet-assembly.md) — is itself a compressed state delivery system. The nine-layer stack converts a raw input signal into a complete, context-saturated packet that contains exactly what the LLM needs and nothing it doesn't:

| What happens | Why it is compression |
|---|---|
| Domain Adapter A classifies the input, extracts `_nlp_anchors` | Raw text → structured evidence partial |
| SLM Context Compression matches against domain physics | Full physics file → relevant invariants only |
| Module State assembles entity profile + current task | Session history → current position |
| Assembled prompt contract | All of the above → one packet |

At each layer, a potentially unbounded raw source (full conversation history, full physics document, raw sensor stream) is compressed down to what is relevant for this turn. The LLM receives the output of the entire compression stack.

---

## THE DETERMINISTIC MATH PRINCIPLE

A critical constraint: **the compression must be code, not model inference.**

All trajectory classification, EWMA computation, mastery estimation, ZPD band calculation, NLP anchor extraction — none of this is delegated to the LLM. These are all deterministic operations:

- They produce the same output for the same input, every time.
- They can be unit-tested without a model.
- They do not hallucinate.
- They do not expand scope.
- They cannot be manipulated by injection into their inputs.

If the LLM were asked to estimate whether load is trending up or down from raw samples, an adversarially-crafted message could potentially influence that estimate. When the estimate is produced by EWMA code before the LLM ever sees the context, there is no injection surface.

---

## THE DUAL-FORMAT OUTPUT DESIGN

The telemetry window makes explicit a design choice that is implicit in the other layers: produce two formats of the same compressed state.

**`json_summary`** — a named-key dict that is human-readable and LLM-readable. Field names like `load_trajectory` and `curve` are meaningful tokens; the LLM can reason over their values in natural language context.

**`numeric_vector`** — a fixed-length float array for use by deterministic code. The resource monitor daemon's threshold checks and the black-box trigger system can evaluate `vector[0] > 0.85` without any model involvement. Fast, cheap, reliable.

This dual-format output should be considered a pattern for any new compressed state summary:

- Name the fields meaningfully for model context.
- Provide a compact numeric encoding for code-side threshold evaluation.
- Keep the two in sync — both come from the same computation, not separate paths.

---

## SECURITY NOTES

The compressed state pattern provides a meaningful security benefit alongside its accuracy benefit:

- **Reduced hallucination surface** — the model doesn't need to guess at context it wasn't given, so speculative outputs based on fabricated context are less likely.
- **Reduced injection surface** — raw data that travels from user input to model context is an injection vector. Data that is transformed by deterministic code before reaching the model carries only what the code computed — adversarial additions that survive NLP normalization still must pass through the math layer before any result enters the model.
- **Scope containment** — a compressed summary is narrower than raw data. The model's reasoning is bounded to the fields in the summary, not to anything that might be inferred from a raw telemetry stream.

---

## SEE ALSO

- [`telemetry-and-blackbox(7)`](telemetry-and-blackbox.md) — full technical detail on the sliding window implementation
- [`prompt-packet-assembly(7)`](prompt-packet-assembly.md) — the nine-layer prompt assembly stack
- [`slm-compute-distribution(7)`](slm-compute-distribution.md) — SLM's role in context compression (Layer 2½)
- [`memory-spec(7)`](memory-spec.md) — entity profile structure and session state compression
- [`resource-monitor-daemon(7)`](resource-monitor-daemon.md) — daemon that consumes the numeric vector
