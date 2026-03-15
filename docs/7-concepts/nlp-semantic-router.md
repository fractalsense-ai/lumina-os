# NLP Semantic Router

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-13

---

This document describes how incoming messages and signals are classified and pre-processed before the D.S.A. orchestrator assembles the prompt contract. The NLP layer is the entry-point director — it determines which domain should handle the input and what structured signals the LLM should receive as grounding anchors.

---

## A. What Is the Semantic Router?

Every input to Lumina — whether a student message, a sensor value, a lab instrument event, or an API call — passes through a two-phase NLP layer before the prompt contract is assembled. This layer serves as the **semantic router**: it normalizes raw, unstructured input into structured signals the rest of the system can act on deterministically.

The system does not require the LLM to infer the domain from context. The NLP layer classifies the input first, narrows the operational boundary, and injects deterministic anchors so the LLM starts from a verified prior rather than an open guess.

Two actions happen in sequence on every input:

1. **Domain classification** — which domain should own this request?
2. **Anchor extraction** — what structured signals can be deterministically extracted from this input before the LLM sees it?

These two phases are architecturally separate and owned at different levels: classification is a system-level concern, anchor extraction is a domain-level concern.

---

## B. Two-Tier Architecture

The NLP layer is split into two distinct tiers. They operate sequentially on the same incoming message but are owned by different parts of the system.

| Tier | Name | Owner | Location | Output |
|------|------|-------|----------|--------|
| 1 | **Semantic Domain Classifier** | Core engine | `src/lumina/core/nlp.py` | `{domain_id, confidence, method}` or `None` |
| 2 | **Domain NLP Pre-Interpreter** | Domain pack | `domain-packs/<domain>/systools/nlp_pre_interpreter.py` | `evidence` dict + `_nlp_anchors` list |

### Tier 1 — Semantic Domain Classifier

`classify_domain(text, domain_map, accessible_domains)` in `src/lumina/core/nlp.py` matches the incoming message against the keyword list for each registered domain in the active registry (`cfg/domain-registry.yaml`). It returns the best-matching domain above a confidence threshold, or `None` to fall back to the configured default.

**Classification procedure (two passes):**

**Pass 1 — Keyword matching**

Each domain's keyword list is evaluated against the lowercased input text. A score is computed as `hits / total_keywords` and scaled. If the best score meets the confidence threshold (`0.6`), classification stops and returns the result.

```python
# src/lumina/core/nlp.py — simplified
hits = sum(1 for kw in keywords if kw.lower() in text_lower)
score = hits / len(keywords)
confidence = min(score * 2.0, 1.0)   # 1 hit out of 5 keywords → 0.4 raw → 0.8 scaled
```

**Pass 2 — spaCy vector similarity**

When keyword matching does not produce a confident result and spaCy is available with a vector model, semantic vector similarity is computed against each domain's label and description. spaCy is a soft dependency — when unavailable, the system degrades gracefully to keyword-only mode.

**Return value:**

```python
{"domain_id": "education", "confidence": 0.8, "method": "keyword"}
# or None — caller falls back to registry default_domain
```

### Tier 2 — Domain NLP Pre-Interpreter

Once the domain is established, the domain pack's NLP pre-interpreter runs before the LLM prompt is assembled. This is **Phase A** of the domain adapter pipeline (see [`domain-adapter-pattern(7)`](domain-adapter-pattern.md) for the full Phase A/B lifecycle). Its job is to extract deterministic structured signals from the raw input and inject them as `_nlp_anchors` into the LLM context.

The education pre-interpreter extracts four signal classes:

| Extractor | Fields produced | Mechanism |
|-----------|----------------|-----------|
| `extract_answer_match` | `correctness`, `extracted_answer` | Regex patterns for `x = N`, "answer is N", bare integer |
| `extract_frustration_markers` | `frustration_marker_count`, `markers` | Keyword regex + ALL\_CAPS ratio + punctuation count |
| `extract_hint_request` | `hint_used` | Keyword regex ("help me", "I'm stuck", "give me a hint") |
| `extract_off_task_ratio` | `off_task_ratio` | Math vocabulary overlap as fraction of total tokens |

The injected anchors are prepended to the LLM context hint, tagged as deterministic:

```
NLP pre-analysis (deterministic):
- correctness: correct (confidence: 0.95) — matched answer "4" to expected "x = 4"
- frustration_marker_count: 0
- off_task_ratio: 0.1
Use these as starting values. Override if your analysis disagrees.
```

The LLM may override them, but having deterministic anchors as a prior makes overrides the exception rather than the rule. This is the core reliability contribution of the NLP layer.

---

## C. Three-Stage Input Pipeline

A single incoming message passes through three sequential stages before it reaches the LLM. The first two stages may short-circuit the pipeline entirely — the third stage always runs when the pipeline reaches the orchestrator.

```
Incoming message / signal
          │
          ▼
┌─────────────────────────────────┐
│ Stage 1: Domain Classification  │  classify_domain() → domain_id
│ (src/lumina/core/nlp.py)        │  or None → fall back to default
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Stage 2: Glossary Intercept     │  Known term? → return inline
│ (domain-lib glossary check)     │  definition; skip orchestrator
└────────────────┬────────────────┘
                 │ (not a glossary hit)
                 ▼
┌─────────────────────────────────┐
│ Stage 3: NLP Anchor Extraction  │  Phase A extractor → _nlp_anchors
│ (domain NLP pre-interpreter)    │  injected into prompt context
└────────────────┬────────────────┘
                 │
                 ▼
          D.S.A. Orchestrator
```

### Stage 2 — Glossary Intercept (short-circuit)

When the incoming text matches a term in the domain's glossary, the system returns an inline definition directly without entering the D.S.A. orchestrator. This is not routing in the classification sense — it is a deterministic early exit that avoids unnecessarily consuming an LLM turn for a known definitional query.

The prompt contract type for these responses is `definition_lookup`, and the returned packet carries the `glossary_entry` field with term, definition, example in context, and related terms.

Only terms explicitly enumerated in the active domain's `glossary` block (in `domain-physics.yaml`) trigger this intercept. Unknown terms pass through to Stage 3.

### Stage 3 — NLP Anchor Extraction (always runs on orchestrator path)

Anchor extraction runs for every message that reaches the orchestrator. Anchors become part of the evidence dict and are formatted into the LLM context hint before the prompt contract is finalized. They do not influence domain classification — they influence LLM interpretation accuracy within the already-established domain.

---

## D. Routing Surface: Keywords and Glossary Evolution

The routing surface for domain classification is defined by the `keywords` list in `cfg/domain-registry.yaml` (one list per domain). A domain's routing surface is as wide as its keyword list.

```yaml
# cfg/domain-registry.yaml
domains:
  education:
    keywords:
      - algebra
      - equation
      - math
      - solve
      - variable
      - tutoring

  agriculture:
    keywords:
      - crop
      - yield
      - soil
      - harvest
      - irrigation
      - agriculture
```

**Current design:** Keywords are manually maintained by each domain's authority. They represent the minimum viable routing surface — enough to classify the most common unambiguous inputs.

**Natural evolution:** A domain's glossary, embedded in `domain-physics.yaml`, contains the full controlled vocabulary for that domain. Glossary terms are a richer and more complete routing surface than a hand-maintained keyword list. As domains mature, the intended direction is for the routing surface to be seeded from the domain glossary rather than maintained separately — making the domain physics the single authoritative source of domain vocabulary at every layer.

This evolution is a domain-level concern (each domain authority decides when to promote glossary terms to routing keywords) and does not require core engine changes.

**System-level routing note:** The `system` domain — responsible for admin operations, auditor access, and runtime configuration changes — will eventually require its own domain physics and glossary to classify inputs at the system level. This is a planned future slice and is tracked separately.

---

## E. Scope Boundaries

The NLP semantic router has a strictly bounded role. Understanding what it does *not* do is as important as understanding what it does.

| The router... | Does NOT... |
|---------------|-------------|
| Classifies which domain owns the input | Apply domain policy (that is Domain Physics) |
| Extracts deterministic signals as anchors | Decide what action the orchestrator should take |
| Short-circuits on known glossary terms | Determine the LLM's response |
| Injects grounding anchors into the LLM context hint | Verify the LLM's output (that is Tool Adapters) |
| Operates synchronously before prompt assembly | Write to the CTL |
| Uses only the message text and registry keywords | Authenticate or authorize the caller |

The NLP layer influences the **quality of the LLM's input**. It does not influence the orchestrator's policy constraints, the tool verification chain, or the ledger. A misconfigured NLP layer can degrade LLM accuracy; it cannot cause a policy violation or a CTL integrity failure — those are protected by separate layers.

---

## SEE ALSO

- [`src/lumina/core/nlp.py`](../../src/lumina/core/nlp.py) — `classify_domain()` implementation; spaCy lazy loader; sentence splitter and tokenizer
- [`cfg/domain-registry.yaml`](../../cfg/domain-registry.yaml) — domain keyword lists; default domain configuration
- [`docs/7-concepts/domain-adapter-pattern.md`](domain-adapter-pattern.md) — Phase A NLP pre-processing and Phase B signal synthesis lifecycle
- [`domain-packs/education/systools/nlp_pre_interpreter.py`](../../domain-packs/education/systools/nlp_pre_interpreter.py) — education domain pre-interpreter (reference implementation)
- [`specs/dsa-framework-v1.md`](../../specs/dsa-framework-v1.md) — D.S.A. structural schema and PPA orchestrator specification
- [`standards/domain-registry-schema-v1.json`](../../standards/domain-registry-schema-v1.json) — schema for `cfg/domain-registry.yaml` including `keywords` field definition
