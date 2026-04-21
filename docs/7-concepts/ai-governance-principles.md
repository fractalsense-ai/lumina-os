---
version: 1.0.0
last_updated: 2026-04-21
---

# Principles of Well-Governed AI Interaction

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-04-21

---

## Overview

This document states the foundational principles that any well-governed AI interaction system must satisfy. They are not implementation prescriptions — they are requirements derived from first principles of systems engineering applied to language model deployment. Each principle is stated as a constraint, followed by the failure mode that occurs when it is violated.

These principles are technology-agnostic. They apply equally to text-based assistants, sensor-driven automation systems, domain-specific tools, and physical control systems. The underlying logic is the same in all cases.

---

## 1. Every Interaction Is a Task

**Principle:** Every interaction between a user and an AI system has a shape, a lifecycle, and a definition of completion. A well-governed system treats this as a first-class structural fact, not an emergent inference.

**The failure mode:** A system that treats interaction as undifferentiated dialogue cannot detect when a task is failing, drifting, or completing. It has no ground truth to check against. Every turn is just another exchange. Drift is invisible until it is catastrophic.

**What this requires:**
- Each task type has a defined turn shape — how many turns are expected, what constitutes progress, what constitutes completion.
- Task state is tracked as a formal structure, not inferred from conversational history.
- Deviation from the expected shape is detectable and measurable.

---

## 2. Context Is Not Conversation

**Principle:** Conversational history (what was said) and operational context (what the system knows) are not the same thing. A well-governed system maintains context as a managed structure. It does not reconstruct context from transcripts.

**The failure mode:** A system that uses conversation history as its primary state store cannot reliably answer: what task is this actor performing, what are the rules governing this interaction, what is the actor's current state relative to their own baseline, what tools are available in this scope. It infers all of these from text. Inference on incomplete context is the root cause of hallucination, drift, and injection.

**What this requires:**
- Operational context is built from structured components: task definition, domain rules, actor state, available tools, turn data.
- Each component is maintained and updated by deterministic code, not inferred by a language model.
- The language model receives context as input. It does not construct context from conversation.

---

## 3. Determinism Must Precede Probability

**Principle:** Anything that can be determined with certainty must be determined before the probabilistic reasoning layer runs. A well-governed system places deterministic gates before the language model, not after.

**The failure mode:** A system that delegates deterministic questions to a language model introduces unnecessary uncertainty at the layer that least tolerates it. Whether an answer is numerically correct, whether a sensor reading is within tolerance, whether an invariant has been violated — these are binary facts. A language model asked to determine them may hallucinate. Deterministic code asked to determine them cannot.

**What this requires:**
- Signal extraction, invariant checking, schema validation, and threshold evaluation are all performed by deterministic code.
- The language model receives the results of these computations as context. It does not perform them.
- Deterministic outputs are explicitly marked as such when injected into the model's context, so the model treats them as facts rather than hypotheses.

---

## 4. Scoped Context, Not Maximum Context

**Principle:** A well-governed system gives each interaction exactly the context it needs for the task at hand and nothing more. Scope is a correctness property, not a performance optimization.

**The failure mode:** A system that provides a language model with everything available — all domain knowledge, all conversation history, all tool definitions — creates noise that the model must filter before reasoning. Noise is an injection surface. It is also an ambiguity surface. The model may reason over irrelevant context as if it were relevant. Narrower scope produces more reliable outputs and eliminates cross-domain contamination structurally rather than by filtering.

**What this requires:**
- Each task type operates within a defined scope: the specific rules, tools, and reference knowledge relevant to that task and no others.
- Context is assembled from scoped sources for each turn. It is not pulled from a global undifferentiated pool.
- A task executing in one domain cannot receive context from another domain through the normal context assembly path.

---

## 5. Behavioral State, Not Conversational History

**Principle:** A well-governed system maintains structured behavioral state for each actor across interactions. It does not re-read conversation history to reconstruct actor state.

**The failure mode:** A system that stores raw conversation history as its actor record cannot answer questions that matter: is this actor's engagement declining? Is their frustration trending upward faster than their baseline? Have they been drifting from the task for three sessions? Conversation transcripts contain the answers to these questions only if someone reads them. Structured behavioral state answers them in O(1).

**What this requires:**
- After each interaction turn, the deterministic components of actor state — skill estimates, engagement signals, affect indicators, task progress — are updated and persisted as structured data.
- Raw conversation content is not the primary state record. Behavioral state is.
- Behavioral state is actor-specific and domain-specific. An actor's state in one domain does not contaminate their state in another.

---

## 6. Floating Baselines, Not Fixed Thresholds

**Principle:** A well-governed system evaluates actor state against that actor's own historical baseline, not against a fixed universal threshold. The relevant signal is rate of change and direction, not absolute position.

**The failure mode:** A system that uses fixed thresholds to detect problems produces false positives for actors whose natural baseline is expressive and false negatives for actors who have shifted dramatically but have not crossed an absolute threshold. An actor whose frustration has tripled from their personal baseline is a stronger signal than an actor who is chronically frustrated but stable.

**What this requires:**
- Baselines are computed per actor from their own interaction history using a smoothing function (e.g., exponential moving average) so they float with the actor over time.
- Invariant checks compare current state to the actor's own baseline, not to a population-level norm.
- Rate of change and direction of change are tracked as first-class signals alongside absolute values.

---

## 7. Every State Change Has a Record

**Principle:** A well-governed system produces a signed, chained record of every state-changing event as it occurs. State changes are not reconstructable from logs after the fact; they are recorded at the time of occurrence.

**The failure mode:** A system that relies on post-hoc log analysis to understand what happened cannot establish causality. Logs record what was said. A ledger records what context the system was operating under when it acted, what invariants were checked, what the actor's state was, and what decision was made and why. Without the ledger, questions like "why did the system escalate at turn seven" or "what was the actor's state when this output was produced" have no authoritative answer.

**What this requires:**
- Every state-mutating operation produces a structured, hash-chained record before the operation is considered complete.
- The record includes not just what happened but the context that governed it: which rules were active, which invariants were checked, what the actor's state was at the moment.
- Records are append-only and form an auditable causal chain from inputs to decisions.

---

## 8. Human Authority Over Real-World Action

**Principle:** A well-governed system does not execute real-world state changes autonomously. Every action that crosses the boundary from language to reality requires explicit human authorization at the time of execution.

**The failure mode:** A system that claims to take real-world action — contacting emergency services, modifying system configuration, executing financial transactions — without a verified connection to real-world systems and explicit human authorization in the pipeline is producing confident-sounding hallucination. A language model has no hands, no phone, no connection to any external system unless that connection is explicitly constructed and governed. Claiming otherwise is not a feature. It is a false safety guarantee.

**What this requires:**
- The boundary between language (proposals, plans, recommendations) and action (execution, mutation, contact with external systems) is architecturally enforced, not described in a system prompt.
- All proposals for real-world action pass through a validation step and a human authorization gate before execution.
- The system is honest about what it can and cannot do. It does not generate the sentence "I have contacted authorities" unless an authenticated, verified connection to those authorities exists and has been used.

---

## 9. Domain Boundaries Are Structural, Not Instructional

**Principle:** A well-governed system enforces domain boundaries through the structure of context assembly, not through instructions to the language model. The model cannot access what was never loaded.

**The failure mode:** A system that tells a language model "you are operating in the education domain, do not discuss system administration" is relying on the model to honor an instruction under adversarial conditions. Instructions can be overridden by prompt injection, by sufficiently persistent conversation, or by model reasoning that concludes the instruction is no longer applicable. Structural isolation cannot be overridden because there is nothing to override — the out-of-scope context was never loaded.

**What this requires:**
- Domain-specific knowledge, tools, and rules are stored in domain-scoped structures that are loaded only when that domain is active for the current interaction.
- Cross-domain contamination is prevented by the storage and retrieval architecture, not by runtime instructions.
- A new domain can be added without any changes to existing domains or the core system, because domains are structurally isolated from each other.

---

## 10. The Language Model Is the Reasoning Layer, Not the Governance Layer

**Principle:** In a well-governed system, the language model reasons over prepared context and produces language. It does not enforce rules, check invariants, maintain state, or make authorization decisions. Those functions belong to deterministic code.

**The failure mode:** A system that delegates governance to the language model has made the probabilistic component responsible for the safety-critical component. The language model is excellent at reasoning under uncertainty, generating language, and synthesizing information. It is unreliable as a rule enforcer because it is fundamentally a pattern-matching system that can always be presented with a pattern that matches "do the thing anyway." Invariants enforced by deterministic code cannot be argued with.

**What this requires:**
- Rule checking, threshold evaluation, scope enforcement, and authorization decisions are performed by deterministic code that runs before and after the model, not by the model itself.
- The model operates within a context that has already been validated. It does not validate its own inputs.
- Model outputs are verified by deterministic tools before they are treated as authoritative on any factual question.

---

## SEE ALSO

- [`context-is-not-conversation(7)`](context-is-not-conversation.md) — the architectural argument behind these principles, with implementation detail
- [`compressed-state-pattern(7)`](compressed-state-pattern.md) — principles 3 and 5 implemented: deterministic compression and behavioral state
- [`domain-pack-anatomy(7)`](domain-pack-anatomy.md) — principle 9 implemented: structural domain isolation
- [`command-execution-pipeline(7)`](command-execution-pipeline.md) — principle 8 implemented: HITL as the universal gate for real-world action
- [`dsa-framework(7)`](dsa-framework.md) — the structural schema (Domain, State, Actor) that these principles produce when applied together