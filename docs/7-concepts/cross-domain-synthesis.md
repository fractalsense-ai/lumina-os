---
version: 1.0.0
last_updated: 2026-03-20
---

# Cross-Domain Synthesis

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-15

---

This document defines how Project Lumina enables controlled, opt-in structural analysis across domain boundaries.  Cross-domain synthesis extends the [Novel Synthesis Framework](novel-synthesis-framework.md) to identify invariant homomorphisms and glossary overlaps between domains that have mutually opted in — without breaking the fundamental isolation guarantees of the domain VLAN model.

---

## A. What Is Cross-Domain Synthesis?

A **cross-domain synthesis** occurs when the system identifies structural similarities between two or more domains — not at the content level (the domains remain independently authoritative) but at the *physics* level: the shape of their invariants, the topology of their standing order chains, and the vocabulary overlaps in their glossaries.

Example:  An education domain and an agriculture domain may both define a "tolerance threshold" invariant that delegates to a subsystem monitor, chains to a "reduce challenge" standing order, and escalates after three attempts.  The **domains** are unrelated, but the **governance patterns** are homomorphic.  Identifying this allows domain authorities to:

- Share proven governance structures without sharing content.
- Discover that a standing order pattern successful in one domain may apply in another.
- Trigger novel synthesis review when the system detects a non-obvious structural bridge.

---

## B. The VLAN Analogy

Each domain in Project Lumina is a fully isolated **Virtual LAN (VLAN)**:

| Network Concept | Lumina Equivalent |
|-----------------|-------------------|
| VLAN tag | `domain_id` |
| VLAN trunk database | `cfg/domain-registry.yaml` |
| Port-based VLAN assignment | `classify_domain()` keyword matching |
| Native VLAN | `default_domain` in registry |
| Inter-VLAN routing | **Cross-domain synthesis** (this feature) |
| Trunk link between switches | Mutual `peer_domains` opt-in |
| Access control list (ACL) | `cross_domain_synthesis.enabled` + mutual peer listing |

**Without cross-domain synthesis**, domains are strictly isolated — each `DomainContext` within a `SessionContainer` never references another domain's state, glossary, or invariants.

**With cross-domain synthesis**, a controlled **trunk link** is established between two domains during night cycle processing.  This link:

- Is **read-only**: no domain modifies another's physics.
- Is **opt-in only**: both domains must explicitly enable and list each other.
- Is **batch-only**: analysis runs during the night cycle, never in real-time sessions.
- Is **proposal-based**: findings require **dual domain authority approval** before recording.

---

## C. Opt-In Configuration

Cross-domain synthesis is configured in each domain's `domain-physics.yaml`:

```yaml
cross_domain_synthesis:
  enabled: true                   # opt in to cross-domain analysis
  peer_domains:                   # which domains to compare with
    - agriculture                 # must be mutual — agriculture must also list education
  share_glossary: true            # include glossary terms in structural comparison
  share_invariant_structure: true # include invariant patterns in physics comparison
```

**Mutual opt-in rule**: Both domains in a pair must list each other in `peer_domains`.  If domain A lists domain B but domain B does not list domain A, no analysis occurs.  This prevents one-sided data exposure.

**Default behaviour**: When `cross_domain_synthesis` is omitted or `enabled: false`, the domain remains fully isolated.  This is the default for all existing domains.

---

## D. Two-Pass Analysis

Cross-domain synthesis runs as a night cycle task and uses a two-pass algorithm:

### Pass 1 — Glossary Structural Comparison

The first pass compares the **glossary index** of each domain pair:

1. Extract all canonical terms and aliases from each domain's glossary.
2. Compute the intersection of term sets.
3. Score: `|shared_terms| / min(|terms_a|, |terms_b|)`.
4. Threshold: 0.15 (at least 15% term overlap to proceed).

This pass identifies **vocabulary bridges** — domains that share conceptual language even if their physics are different.  For example, both an education domain and a project management domain might share terms like "milestone", "assessment", and "progress".

### Pass 2 — Invariant Structure Comparison

The second pass runs only for pairs that passed the glossary threshold (or when glossary data is unavailable):

1. Extract a **structural signature** from each invariant:
   - Severity level (critical / warning)
   - Whether it has a `check` expression
   - Whether it delegates to a subsystem (`handled_by`)
   - Whether it chains to a standing order
   - Whether it emits a `signal_type`
2. Match invariants across domains by structural signature (greedy, one-to-one).
3. Score: `|matched_pairs| / min(|invariants_a|, |invariants_b|)`.

This pass identifies **invariant homomorphisms** — invariants that serve the same structural role across domains regardless of their domain-specific semantics.

---

## E. Dual-Key Domain Authority Approval

Cross-domain synthesis findings produce `Proposal` objects with `required_approvers` set to both domain IDs.  Approval follows a dual-key pattern:

1. The night cycle generates a proposal: `"Cross-domain similarity between education and agriculture: glossary overlap (3 shared terms); invariant structure match (2 pairs)"`
2. The proposal is visible in the governance dashboard for **both** domain authorities.
3. Each DA independently reviews and approves or rejects.
4. **Both must approve** for the proposal to be recorded as `cross_domain_synthesis_verified` in the System Logs.
5. If **either rejects**, the proposal becomes `cross_domain_synthesis_rejected`.

This extends the Novel Synthesis Framework's two-key gate to a **four-key gate**: LLM detection + system analysis + DA₁ approval + DA₂ approval.

---

## F. Domain Pack Integration Guide

To enable cross-domain synthesis for a domain pack:

1. **Add the config block** to `domain-physics.yaml`:
   ```yaml
   cross_domain_synthesis:
     enabled: true
     peer_domains: [other_domain_id]
   ```

2. **Ensure the peer domain reciprocates** — the other domain must list your domain in its `peer_domains`.

3. **Populate the glossary** (recommended) — the more complete your glossary, the better Pass 1 performs.  Domains with no glossary will skip Pass 1 and go directly to invariant comparison.

4. **Review proposals** in the governance dashboard after the next night cycle run.

5. **Record commitment** — approved proposals generate `cross_domain_synthesis_verified` commitment records in the System Logs.

---

## G. Relationship to Novel Synthesis Framework

Cross-domain synthesis is an extension of the [Novel Synthesis Framework](novel-synthesis-framework.md):

| Novel Synthesis | Cross-Domain Synthesis |
|-----------------|------------------------|
| Detects unknown patterns within one domain | Detects structural similarities across domains |
| Key 1: LLM/adapter flags, Key 2: DA confirms | Key 1: glossary pass, Key 2: invariant pass, Key 3+4: both DAs confirm |
| TraceEvent: `novel_synthesis_flagged` | TraceEvent: `cross_domain_synthesis_flagged` |
| CommitmentRecord: `novel_synthesis_verified` / `_rejected` | CommitmentRecord: `cross_domain_synthesis_verified` / `_rejected` |
| Runs in real-time during sessions | Runs in batch during night cycle |
| Single domain authority approves | Both domain authorities must approve |

The system treats cross-domain findings as novel synthesis candidates — they enter the same verification pipeline but with the additional constraint of dual approval.
