# SLM Compute Distribution

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-14  

---

This document explains how Project Lumina uses a Small Language Model (SLM) to distribute compute away from the primary LLM. The SLM handles low-weight tasks — glossary rendering, domain physics context compression, and admin command translation — so the LLM receives only pre-digested, high-quality context when it is invoked.

---

## A. Design Principle

The LLM's reasoning space is finite and expensive. Every token of ambiguity in the prompt packet is a token the LLM must resolve instead of reason. The SLM acts as a pre-processing layer that reduces ambiguity before the packet reaches the LLM.

The operating rule:

> **Low-weight (SLM):** Definitions, formatting, regex validation, simple state updates, physics interpretation, admin command translation.  
> **High-weight (LLM):** Creative skinning, complex problem solving, novelty synthesis, instruction generation, verification requests.

The SLM is **not** a cheaper LLM. It is a dedicated compute tier optimized for structured extraction and template rendering. It never generates instructional content, creative responses, or safety-critical decisions.

---

## B. Architecture

The SLM operates alongside the NLP pipeline — it does not replace or modify it. The NLP classifier (`classify_domain`) and domain pre-interpreters run unchanged. The SLM adds a parallel context compression step and handles tasks that would otherwise waste LLM capacity.

```
                          ┌──────────────────┐
                          │  Input Interface  │
                          └────────┬─────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
              ┌─────▼─────┐               ┌──────▼──────┐
              │    NLP     │               │ Glossary    │
              │ Classifier │               │ Intercept   │
              └─────┬─────┘               └──────┬──────┘
                    │                             │
                    │                     ┌───────▼───────┐
                    │                     │  SLM Render   │──► definition response
                    │                     │  (Librarian)  │    (LLM never invoked)
                    │                     └───────────────┘
              ┌─────▼─────────────┐
              │ Domain Adapter A  │
              │ (Input Normalize) │
              └─────┬─────────────┘
                    │
              ┌─────▼───────────────┐
              │  SLM Physics        │
              │  Interpreter        │──► _slm_context metadata
              │  (Context Compress) │    injected into turn_data
              └─────┬───────────────┘
                    │
              ┌─────▼──────────────┐
              │ Prompt Packet      │
              │ Assembly           │
              └─────┬──────────────┘
                    │
         ┌──────────▼──────────┐
         │  Weight Classifier  │
         └──┬──────────────┬───┘
            │              │
      ┌─────▼─────┐  ┌────▼─────┐
      │ LOW → SLM │  │HIGH → LLM│
      └───────────┘  └──────────┘
```

### Key integration points

1. **Glossary intercept** — when a user's message matches a known glossary term, the SLM renders a fluent definition. The LLM is never called. If the SLM is unavailable, a deterministic template is used (never the LLM).
2. **Physics interpretation** — after NLP classification and input normalization, the SLM matches incoming signals against domain invariants and glossary to produce `_slm_context`. This flows into the prompt packet as pre-digested context.
3. **Weight-routed dispatch** — after the prompt packet is assembled, `classify_task_weight()` determines whether the response should come from the SLM or the LLM.
4. **Admin command translation** — natural language admin instructions are parsed by the SLM into structured operations that execute through existing admin endpoints with full RBAC enforcement.

---

## C. Task Weight Classification

Every prompt type maps to a weight class. The weight boundary determines which model handles the request.

| Weight | Prompt types | Handler |
|--------|-------------|---------|
| **LOW** | `definition_lookup`, `physics_interpretation`, `state_format`, `admin_command`, `field_validation` | SLM |
| **HIGH** | `instruction`, `correction`, `scaffolded_hint`, `more_steps_request`, `novel_synthesis`, `verification_request`, `task_presentation`, `hint` | LLM |

Domain packs can override classifications via `slm_weight_overrides` in their runtime configuration. An unrecognized prompt type defaults to HIGH — it is safer to send unknown work to the LLM than risk a bad SLM response.

---

## D. The Three SLM Roles

### D.1 Librarian — Glossary Response Rendering

When the glossary intercept pattern detects a known term in the user's message, the Librarian renders a fluent, contextualized definition.

**Input:** A glossary entry dict (term, definition, aliases, related terms, example in context).  
**Output:** A natural-language response (2–3 sentences) using only the provided glossary data.  
**Fallback:** If the SLM is unavailable, the system returns a deterministic template: `"{term}: {definition}"`. The LLM is never used as a glossary fallback.

### D.2 Physics Interpreter — Context Compression

Before the prompt packet reaches the LLM, the Physics Interpreter pre-digests incoming signals against domain physics. This compresses the raw context into a structured summary.

**Input:** Incoming signals (NLP anchors, sensor data, tool outputs) + domain physics (invariants, standing orders) + glossary terms.  
**Output:** A `_slm_context` dict containing:
- `matched_invariants` — which invariants are relevant to this turn
- `relevant_glossary_terms` — which terms apply
- `context_summary` — one-sentence summary of what the input means in domain context
- `suggested_evidence_fields` — pre-populated field values for the evidence dict

**Fallback:** Returns an empty context enhancement dict. The prompt packet assembly continues without SLM-compressed context.

The `_slm_context` dict is injected into `turn_data` alongside `_nlp_anchors`. Both are structured metadata that flow into the prompt packet. The NLP pipeline is unchanged — the SLM adds context, it does not replace NLP classification.

### D.3 Command Translator — Admin Command Parsing

When an authorized admin issues a natural language instruction (e.g., "update the coefficient threshold in algebra to 0.8"), the Command Translator parses it into a structured operation.

**Input:** Natural language instruction + list of available admin operations.  
**Output:** `{"operation": "update_domain_physics", "target": "algebra", "params": {"updates": {"coefficient_threshold": 0.8}}}` — or `null` if unparseable.  
**Execution:** The structured command executes through existing admin endpoints with full RBAC enforcement. The SLM only translates — it does not execute. Unauthorized commands are rejected at the endpoint layer.  
**Available operations:** `update_domain_physics`, `commit_domain_physics`, `update_user_role`, `deactivate_user`, `resolve_escalation`.

---

## E. Provider Architecture

The SLM layer supports three provider backends. Local is the default and recommended configuration.

| Provider | Env var | Default model | Notes |
|----------|---------|---------------|-------|
| **local** (default) | `LUMINA_SLM_ENDPOINT` (`http://localhost:11434`) | `phi-3` | Ollama/llama.cpp via OpenAI-compatible chat endpoint. No API key needed. |
| openai | `OPENAI_API_KEY` | `LUMINA_SLM_MODEL` | Uses OpenAI client library. |
| anthropic | `ANTHROPIC_API_KEY` | `LUMINA_SLM_MODEL` | Uses Anthropic client library. |

Set `LUMINA_SLM_PROVIDER` to select the backend. All providers use the same interface: system prompt + user payload → text response.

The local provider HTTP timeout defaults to 60 seconds and can be overridden with the `LUMINA_SLM_TIMEOUT` environment variable. On modest hardware, physics interpretation prompts may need longer than the default — set `LUMINA_SLM_TIMEOUT=90` (or higher) if server logs show `SLM physics interpretation failed (timed out)` warnings.

### Enterprise scaling

An enterprise deployment may run a small cluster of local SLMs behind a load balancer. The `LUMINA_SLM_ENDPOINT` configuration points to the balancer, and the SLM cluster handles all low-weight traffic. The LLM sees only high-weight, pre-digested prompts.

---

## F. Configuration in System Physics

The `slm_config` block in `system-physics.yaml` controls SLM behaviour system-wide:

```yaml
slm_config:
  enabled: true
  default_provider: local
  weight_boundary: definitions_and_physics
  fallback_on_unavailable: deterministic
  local_endpoint: "http://localhost:11434"
  admin_command_translation: true
  timeout_seconds: 60
```

| Field | Values | Meaning |
|-------|--------|--------|
| `enabled` | `true`/`false` | Master switch for SLM compute distribution |
| `default_provider` | `local`, `openai`, `anthropic` | Which SLM backend to use |
| `weight_boundary` | `definitions_only`, `definitions_and_physics`, `full` | How much work the SLM handles |
| `fallback_on_unavailable` | `deterministic`, `llm` | What to do when SLM is unreachable. `deterministic` (recommended) uses templates; `llm` falls back to the LLM |
| `local_endpoint` | URI string | Ollama/llama.cpp endpoint for local provider |
| `admin_command_translation` | `true`/`false` | Whether the Command Translator role is enabled |
| `timeout_seconds` | number (≥ 5) | HTTP timeout in seconds for local SLM calls. Override at runtime via `LUMINA_SLM_TIMEOUT`. Default: `60` |

---

## G. Provenance and Audit

When the SLM handles a turn, the CTL trace event records `slm_model_id` in provenance metadata. This ensures every SLM decision is attributable to a specific model version.

For admin command translation, the CTL commitment record includes `slm_command_translation` metadata documenting the original natural language instruction and the parsed structured command.

---

## H. Fallback Guarantees

The SLM layer is designed to degrade gracefully. If the SLM is unavailable:

| Role | Fallback | Impact |
|------|----------|--------|
| Librarian | Deterministic template: `"{term}: {definition}"` | Definition still returned; less fluent, no related terms woven in |
| Physics Interpreter | Empty context dict (no enhancement) | LLM receives uncompressed context; works but uses more reasoning tokens |
| Command Translator | HTTP 503 with retry guidance | Admin must retry or use structured API directly |
| Weight-routed LOW tasks | SLM availability checked; if unavailable, falls back per `fallback_on_unavailable` config | Either deterministic or LLM depending on policy |

The critical invariant: **SLM failure never blocks the system.** It degrades quality (less pre-digested context, less fluent definitions) but never prevents operation.

---

## I. Zero-Trust Alignment

The SLM operates under the same zero-trust guarantees as the rest of the system:

- SLM outputs are structured and parsed — free-text SLM responses are JSON-parsed with strict key validation. Malformed responses trigger the deterministic fallback.
- Admin commands are RBAC-enforced — the SLM only translates; execution goes through existing admin endpoints that check `can_govern_domain()`, role permissions, and RBAC policy.
- Provenance is recorded — every SLM interaction produces a CTL trace with model identity.
- No scope expansion — the SLM cannot introduce new prompt types, create new admin operations, or modify domain physics directly. It operates within the boundaries defined by the weight classification table and the admin operations list.

---

## J. Related Documents

- [Prompt Packet Assembly](prompt-packet-assembly.md) — How the assembled prompt contract is built from layered components
- [Domain Adapter Pattern](domain-adapter-pattern.md) — How domain packs extend the core engine
- [NLP Semantic Router](nlp-semantic-router.md) — Classification pipeline that runs alongside the SLM
- [Zero-Trust Architecture](zero-trust-architecture.md) — Trust boundary model for all system components
