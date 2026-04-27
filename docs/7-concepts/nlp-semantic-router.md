---
version: 1.1.0
last_updated: 2026-03-27
---

# NLP Semantic Router

**Version:** 1.1.0
**Status:** Active
**Last updated:** 2026-03-27

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
| 2 | **Domain NLP Pre-Interpreter** | Domain pack | `model-packs/<domain>/controllers/nlp_pre_interpreter.py` | `evidence` dict + `_nlp_anchors` list |

### Tier 1 — Semantic Domain Classifier

`classify_domain(text, domain_map, accessible_domains)` in `src/lumina/core/nlp.py` matches the incoming message against the keyword list for each registered domain in the active registry (`cfg/domain-registry.yaml`). It returns the best-matching domain above a confidence threshold, or `None` to fall back to the configured default.

**Classification procedure (three passes):**

**Pass 1 — Keyword matching**

Each domain's keyword list is evaluated against the lowercased input text. A score is computed as `hits / total_keywords` and scaled. If the best score meets the confidence threshold (`0.6`), classification stops and returns the result.

```python
# src/lumina/core/nlp.py — simplified
hits = sum(1 for kw in keywords if kw.lower() in text_lower)
score = hits / len(keywords)
confidence = min(score * 2.0, 1.0)   # 1 hit out of 5 keywords → 0.4 raw → 0.8 scaled
```

**Pass 1.5 — Vector routing via global store**

When keyword matching is inconclusive and the `VectorStoreRegistry` has been injected (via `set_vector_registry()`), the classifier queries the `_global` per-domain vector store for the top-5 nearest neighbours of the input text.  Each hit votes for its `domain_id`; the domain with the highest average cosine similarity score above the confidence threshold is selected.

This pass uses domain-tuned embeddings (built from actual domain content by the Edge Vectorization housekeeper) rather than general-purpose word vectors, producing more accurate classification for specialised vocabulary.  For full details on the per-domain vector layout and the global routing index, see [`edge-vectorization(7)`](edge-vectorization.md) §E–F.

Vector routing is a **soft dependency** — when the registry is not configured or the global store is empty, this pass is silently skipped and classification falls through to Pass 2.

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

## C. Four-Stage Routing Decision

A single incoming message passes through four stages to determine which domain owns it. Stages 1 and 2 may resolve the domain early; Stage 3 handles authenticated users who match no NLP signal; Stage 4 is the final safety net.

```
Incoming message / signal
          │
          ▼
┌──────────────────────────────────────┐
│ Stage 1: Explicit domain_id          │  domain_id in request body → done
│ (API request field)                  │  validates against registry
└────────────────┬─────────────────────┘
                 │ (no domain_id)
                 ▼
┌──────────────────────────────────────┐
│ Stage 2: NLP Semantic Classification │  classify_domain() → domain_id
│ (src/lumina/core/nlp.py)             │  confidence ≥ 0.6 → done
└────────────────┬─────────────────────┘
                 │ (confidence < 0.6 or NLP unavailable)
                 ▼
┌──────────────────────────────────────┐
│ Stage 3: Role-Based Default          │  resolve_default_for_user(user)
│ (domain_registry.py)                 │  root/super_admin → system
│                                      │  admin → governed domain
└────────────────┬─────────────────────┘
                 │ (role not in role_defaults, or unauthenticated)
                 ▼
┌──────────────────────────────────────┐
│ Stage 4: Global Default              │  default_domain in registry
│ (cfg/domain-registry.yaml)           │  → education (masks system internals)
└──────────────────────────────────────┘
```

### Stage 3 — Role-Based Default Fallback

When NLP classification does not find a confident match, authenticated users may be directed to a domain that matches their role rather than the global default. This is controlled by two fields in `cfg/domain-registry.yaml`:

**`role_defaults`** — maps role names to domain IDs:
```yaml
role_defaults:
  root: system
  super_admin: system
```

**`module_prefix`** per domain entry — enables reverse-mapping a module path to a domain:
```yaml
domains:
  education:
    module_prefix: edu
  agriculture:
    module_prefix: agri
  system:
    module_prefix: sys
```

**Resolution algorithm** (`DomainRegistry.resolve_default_for_user()`):

1. `user is None` (unauthenticated) → Stage 4 global default
2. `role` found in `role_defaults` → that domain (e.g. `root` → `system`)
3. `role == admin` and `governed_modules` non-empty → extract prefix from first module path (`domain/<prefix>/…`) and look up in `module_prefix` reverse map
4. Fallthrough → Stage 4 global default

**Design rationale:** The global `default_domain` is deliberately set to `education` (a domain-level domain) to ensure that system internals remain invisible to unauthenticated users and domain-level roles. System operators (`root`, `super_admin`) who send a message with no explicit domain receive the system domain, which is their natural working context. Domain authorities land in the domain they govern.

**Roles not in `role_defaults`:** `operator`, `half_operator`, and `user` are cross-cutting readers; they are not operators of any specific domain by default, so they fall through to the global default (education). They can reach any domain they have permission for by specifying `domain_id` explicitly.

### Stage 2 + Stage 3 interaction: accessible domain filtering

Before calling `classify_domain()` (Stage 2), the server builds an `accessible_domains` list by checking EXECUTE permission on every registered domain for the authenticated user. Only accessible domains are passed to the NLP classifier. This prevents the classifier from routing a user to a domain they cannot access.

For `root` users, all domains are accessible (permission check is bypassed).

---

## D. Input Processing Pipeline (post-routing)

After the domain is resolved, the input passes through three sequential processing stages before reaching the LLM. The first two stages may short-circuit the pipeline entirely.

```
Incoming message / signal
          │
          ▼
┌─────────────────────────────────┐
│ Phase A: Domain Classification  │  classify_domain() → domain_id
│ (Stages 1-4 above)              │  or role-based/global default
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Phase B: Glossary Intercept     │  Known term? → return inline
│ (domain-lib glossary check)     │  definition; skip orchestrator
└────────────────┬────────────────┘
                 │ (not a glossary hit)
                 ▼
┌─────────────────────────────────┐
│ Phase C: NLP Anchor Extraction  │  Phase A extractor → _nlp_anchors
│ (domain NLP pre-interpreter)    │  injected into prompt context
└────────────────┬────────────────┘
                 │
                 ▼
          D.S.A. Orchestrator
```

### Phase B — Glossary Intercept (short-circuit)

When the incoming text matches a term in the domain's glossary, the system returns an inline definition directly without entering the D.S.A. orchestrator. This is not routing in the classification sense — it is a deterministic early exit that avoids unnecessarily consuming an LLM turn for a known definitional query.

The prompt contract type for these responses is `definition_lookup`, and the returned packet carries the `glossary_entry` field with term, definition, example in context, and related terms.

Only terms explicitly enumerated in the active domain's `glossary` block (in `domain-physics.yaml`) trigger this intercept. Unknown terms pass through to Phase C.

### Phase C — NLP Anchor Extraction (always runs on orchestrator path)

Anchor extraction runs for every message that reaches the orchestrator. Anchors become part of the evidence dict and are formatted into the LLM context hint before the prompt contract is finalized. They do not influence domain classification — they influence LLM interpretation accuracy within the already-established domain.

---

## E. Routing Surface: Keywords and Glossary Evolution

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

---

## F. Scope Boundaries

The NLP semantic router has a strictly bounded role. Understanding what it does *not* do is as important as understanding what it does.

| The router... | Does NOT... |
|---------------|-------------|
| Classifies which domain owns the input | Apply domain policy (that is Domain Physics) |
| Extracts deterministic signals as anchors | Decide what action the orchestrator should take |
| Short-circuits on known glossary terms | Determine the LLM's response |
| Injects grounding anchors into the LLM context hint | Verify the LLM's output (that is Tool Adapters) |
| Operates synchronously before prompt assembly | Write to the System Logs |
| Uses only the message text and registry keywords | Authenticate or authorize the caller |

The NLP layer influences the **quality of the LLM's input**. It does not influence the orchestrator's policy constraints, the tool verification chain, or the ledger. A misconfigured NLP layer can degrade LLM accuracy; it cannot cause a policy violation or a System Log integrity failure — those are protected by separate layers.

---

## SEE ALSO

- [`src/lumina/core/nlp.py`](../../src/lumina/core/nlp.py) — `classify_domain()` implementation; spaCy lazy loader; sentence splitter and tokenizer
- [`cfg/domain-registry.yaml`](../../cfg/domain-registry.yaml) — domain keyword lists; default domain configuration
- [`docs/7-concepts/domain-adapter-pattern.md`](domain-adapter-pattern.md) — Phase A NLP pre-processing and Phase B signal synthesis lifecycle
- [`docs/7-concepts/edge-vectorization.md`](edge-vectorization.md) — per-domain vector stores, global routing index, and Pass 1.5 detail
- [`model-packs/education/controllers/nlp_pre_interpreter.py`](../../model-packs/education/controllers/nlp_pre_interpreter.py) — education domain pre-interpreter (reference implementation)
- [`specs/dsa-framework-v1.md`](../../specs/dsa-framework-v1.md) — D.S.A. structural schema and PPA orchestrator specification
- [`standards/domain-registry-schema-v1.json`](../../standards/domain-registry-schema-v1.json) — schema for `cfg/domain-registry.yaml` including `keywords` field definition
- [`model-packs/education/controllers/governance_adapters.py`](../../model-packs/education/controllers/governance_adapters.py) — `_deterministic_command_fallback()` — domain-specific verb/noun routing for admin commands (invite, modify, deactivate)
