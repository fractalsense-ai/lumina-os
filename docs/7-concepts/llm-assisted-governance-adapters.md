---
version: 1.0.0
last_updated: 2026-04-03
---

# LLM-Assisted Governance Adapters

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-04-03  

---

## A. Problem Statement

Domain packs that include governance modules (Domain Authority, Ingestion
Review, Role Management) share the engine's LLM pipeline with content-delivery
modules. Without separation, the LLM receives a content persona
(e.g. algebra tutor) while processing governance requests — producing responses
that bleed subject matter into administrative output.

This document describes the **governance adapter pattern**: a reusable
architecture for giving governance modules their own persona, turn
interpretation, command dispatch, and structured action cards, all without
modifying the core engine.

---

## B. Architecture Overview

```
┌───────────────────────────────────────────────────────┐
│                   Chat Input                          │
└────────────┬──────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────┐
│   NLP Domain Classifier    │  ← Tier 1: picks domain
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  Module Router (module_map)│  ← resolves active module
└────────────┬───────────────┘
             │
     ┌───────┴────────┐
     │ is governance?  │
     └───┬─────────┬───┘
        YES        NO
         │          │
         ▼          ▼
┌──────────────┐ ┌──────────────┐
│  Governance  │ │   Content    │
│   Persona    │ │   Persona    │
│   + Turn     │ │   + Turn     │
│   Interp     │ │   Interp     │
└──────┬───────┘ └──────┬───────┘
       │                │
       ▼                ▼
┌──────────────┐ ┌──────────────┐
│  Task Weight │ │  Task Weight │
│  governance_ │ │  learning_*  │
│  (LOW→SLM)   │ │  (HIGH→LLM)  │
└──────┬───────┘ └──────┬───────┘
       │                │
       ▼                ▼
┌──────────────────────────────┐
│   Shared Processing Pipeline │
│   (staging, HITL, commit)    │
└──────────────────────────────┘
```

The per-module override mechanism allows each module_map entry in
`runtime-config.yaml` to declare its own `domain_system_prompt_path` and
`turn_interpretation_prompt_path`. The runtime loader pre-compiles these at
startup and the processing layer shallow-copies the runtime to inject them
before LLM invocation.

---

## C. The Four Layers of Separation

Governance adapters prevent context bleed at four distinct layers:

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| **1. Persona** | `governance-persona-v1.md` | Replaces content persona (algebra, agriculture, etc.) with administrative rendering rules |
| **2. Turn Interpretation** | `governance-turn-interpretation-spec-v1.md` | SLM evidence schema shaped for commands/status queries instead of learning metrics |
| **3. Task Weight** | `governance_*` weight types in `TaskWeight` | Routes low-weight governance turns (status, progress) to SLM; reserves LLM for `governance_command` |
| **4. Command Dispatch** | `interpret_turn_input()` + deterministic fallback | Classifies governance intents, routes to admin operations, builds structured action cards |

### Layer 1 — Governance Persona

A governance persona file defines `rendering_rules` for administrative
task types. Unlike content personas that describe subject matter presentation, a
governance persona specifies how to present command confirmations, status
summaries, escalation reports, and progress indicators.

```yaml
# runtime-config.yaml — governance module_map entry
module_map:
  domain-authority:
    controller: governance_adapters
    domain_system_prompt_path: prompts/governance-persona-v1.md
    turn_interpretation_prompt_path: prompts/governance-turn-interpretation-spec-v1.md
    turn_interpreter: adapter/edu/governance/v1
```

### Layer 2 — Governance Turn Interpretation

Content turn-interpretation specs include fields like `correctness`,
`hint_used`, and `off_task_ratio`. A governance turn-interpretation spec
replaces these with governance-relevant fields:

- `query_type` — governance_general | governance_command | governance_status |
  governance_progress | governance_management | governance_escalation
- `command_dispatch` — `{ operation, target, params }`
- `target_component` — which subsystem the request targets

### Layer 3 — Task Weight Classification

The `TaskWeight` enum includes governance-specific types that prevent
unnecessary LLM invocation for read-only governance requests:

| Weight Type | Classification | Routed To |
|-------------|---------------|-----------|
| `governance_general` | LOW | SLM |
| `governance_status` | LOW | SLM |
| `governance_progress` | LOW | SLM |
| `governance_escalation` | LOW | SLM |
| `governance_management` | LOW | SLM |
| `governance_command` | HIGH | LLM |

Only `governance_command` — which triggers state-mutating admin operations —
requires the full LLM. All other governance interactions are handled by the
SLM or deterministic paths.

### Layer 4 — Command Dispatch

The `interpret_turn_input()` function in `governance_adapters.py` classifies
governance intents through a two-tier pipeline:

1. **SLM evidence** — the governance turn interpreter produces structured
   evidence with `command_dispatch` fields
2. **Deterministic fallback** — keyword matching catches commands the SLM
   misses (verb-based for physics/ingestion, keyword-based for roles/groups)

When a `governance_command` intent is detected, the processing layer routes
it through the HITL staging pipeline with a structured action card.

---

## D. LLM-Assisted Physics Editing

The governance adapter pattern enables LLM-assisted editing of domain
physics files — the operational configuration that controls domain behaviour.

### The Problem

Physics files are complex JSON structures with invariants, standing orders,
escalation triggers, and glossaries. Requiring domain authorities to write
raw JSON patches is error-prone.

### The Solution

When a DA issues a natural language physics edit instruction, the system:

1. **Extracts a structured patch** — `extract_physics_patch()` sends the
   current physics snapshot and the natural language instruction to the LLM
   with a dedicated system prompt
2. **Pre-populates a proposal form** — the LLM returns a structured proposal
   containing `target_section`, `operation_type`, `proposed_patch`,
   `affected_ids`, `diff_summary`, and `confidence`
3. **Stages through HITL** — the proposal follows the standard `_stage_command`
   pipeline; the DA reviews the pre-populated form before committing
4. **Detects novel synthesis** — `detect_novel_synthesis()` compares the
   proposed patch against existing physics entries and flags genuinely new
   concepts for provenance tracking

### Physics Edit Flow

```
DA: "Add an invariant that group presentations must cite sources"
        │
        ▼
┌──────────────────────────────┐
│  extract_physics_patch()     │
│  ┌────────────────────────┐  │
│  │ System Prompt:         │  │
│  │ "You are a physics     │  │
│  │  editor. Return JSON   │  │
│  │  with target_section,  │  │
│  │  operation_type, ..."  │  │
│  └────────────────────────┘  │
│  Input: current physics +    │
│         NL instruction       │
│  Output: structured proposal │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  _stage_command()            │
│  Creates StagedCommand with  │
│  enriched params from patch  │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  build_physics_edit_card()   │
│  Action card with:           │
│  - current_snapshot          │
│  - proposed_patch            │
│  - diff_summary              │
│  - confidence score          │
│  - Accept / Modify / Reject  │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  detect_novel_synthesis()    │
│  Flags new IDs not in        │
│  existing physics → trace    │
└──────────────────────────────┘
```

### Escalation Gating

When a Teacher or TA (rather than the DA) issues a physics edit, the system
sets `requires_escalation: true`. The staged command is still created, but
the action card indicates that DA approval is required. The existing
EscalationRecord mechanism handles the approval workflow.

---

## E. Document Ingestion Integration

Governance adapters also wire the document ingestion pipeline into the
conversational interface.

### Tool Adapter Declaration

Each governance module that supports ingestion declares a tool adapter:

```yaml
# tool-adapters/ingestion-adapter-v1.yaml
adapter_id: adapter/edu/ingestion/v1
call_types:
  - list_ingestions
  - review_ingestion
  - approve_interpretation
  - reject_ingestion
authorization:
  allowed_roles:
    - domain_authority
    - teacher
```

### Ingestion Config in Physics

The module's `domain-physics.json` includes an `ingestion_config` section:

```json
{
  "ingestion_config": {
    "enabled": true,
    "max_file_size_mb": 10,
    "accepted_formats": ["pdf", "docx", "markdown", "csv", "json", "yaml"],
    "max_interpretations": 3
  }
}
```

### Command Routing

The deterministic fallback in `interpret_turn_input()` catches ingestion
verbs (`ingest`, `upload`, `import`) and ingestion keywords (`approve`,
`reject`, `review`, `interpretation`) to route them to the correct admin
operations. An `ingestion_review` action card is presented for review
operations, showing available interpretations and their confidence scores.

---

## F. Novel Synthesis Detection

When physics edits introduce genuinely new concepts — IDs that do not
exist in any current physics section — the system flags them as novel
synthesis events.

The `detect_novel_synthesis()` function:

1. Identifies which physics sections carry structured IDs (invariants,
   standing orders, escalation triggers, glossary entries, artifacts)
2. Collects all existing IDs from those sections
3. Compares proposed patch entries against the existing set
4. Returns a list of IDs that represent net-new concepts

Novel synthesis events are recorded as provenance traces with
`novel_synthesis_signal: "NOVEL_PATTERN"`, connecting the physics editing
workflow to the broader [novel synthesis framework](novel-synthesis-framework.md).

---

## G. Implementing for a New Domain Pack

To add governance adapters to a new domain pack:

1. **Create a governance persona** — define `rendering_rules` for each
   `governance_*` task type; omit all subject-matter content
2. **Create a governance turn-interpretation spec** — replace content-specific
   SLM fields with `query_type`, `command_dispatch`, `target_component`
3. **Register in runtime-config.yaml** — set `domain_system_prompt_path` and
   `turn_interpretation_prompt_path` on each governance module_map entry
4. **Implement `interpret_turn_input()`** — two-tier: SLM evidence parsing +
   deterministic keyword fallback
5. **Add tool adapter YAMLs** — declare admin operations and RBAC gates for
   each governance capability (physics editing, ingestion, role management)
6. **Configure ingestion** — add `ingestion_config` to domain-physics.json
   if the module supports document ingestion

### What NOT to Do

- **Do not reuse content personas for governance.** The LLM will produce
  subject-matter framing around administrative output.
- **Do not skip the deterministic fallback.** SLM evidence alone is
  insufficient for reliable command routing.
- **Do not classify `governance_command` as LOW weight.** Physics edits and
  role changes require full LLM processing with the governance persona.
- **Do not bypass HITL for physics edits.** All state-mutating operations
  must pass through the staging pipeline regardless of actor role.

---

## References

- [domain-adapter-pattern](domain-adapter-pattern.md) — foundational adapter
  architecture; governance adapters are a specialisation of this pattern
- [command-execution-pipeline](command-execution-pipeline.md) — three-stage
  pipeline (Proposal → HITL → Commit) used for all governance commands
- [slm-compute-distribution](slm-compute-distribution.md) — task weight
  classification and SLM/LLM routing that governance adapters leverage
- [novel-synthesis-framework](novel-synthesis-framework.md) — novel synthesis
  detection integrated into physics editing
- [ingestion-pipeline](ingestion-pipeline.md) — document ingestion lifecycle
  wired through governance command dispatch

### Source Files

| File | Role |
|------|------|
| `domain-packs/education/controllers/governance_adapters.py` | Reference implementation: state builder, turn interpreter, physics patch extraction, novel synthesis |
| `domain-packs/education/prompts/governance-persona-v1.md` | Education governance persona |
| `domain-packs/education/prompts/governance-turn-interpretation-spec-v1.md` | Governance SLM evidence schema |
| `domain-packs/education/cfg/runtime-config.yaml` | Module_map entries with per-module overrides |
| `src/lumina/core/runtime_loader.py` | Pre-compiles per-module system prompts and turn interpretation specs |
| `src/lumina/api/processing.py` | LLM-assisted physics editing orchestration |
| `src/lumina/api/structured_content.py` | Action card builders for physics edits and ingestion review |
| `src/lumina/core/slm.py` | TaskWeight enum with governance_* classifications |
| `standards/physics-edit-proposal-schema-v1.json` | Schema for physics edit proposal action cards |
