---
version: 1.2.0
last_updated: 2026-03-30
---

# Domain Pack Anatomy

**Version:** 1.2.0  
**Status:** Active  
**Last updated:** 2026-03-30  

---

A domain pack is the fundamental unit of domain knowledge and bounded authority in Project
Lumina. Understanding what a domain pack *is* — as a design pattern, not just a directory
structure — is the prerequisite for understanding how Lumina separates domain concerns from
system concerns, why every domain owns its own NLP pre-processor, and why the physics file
is the domain's law rather than its executor.

---

## A. What Is a Domain Pack?

A domain pack is the **D pillar** of the D.S.A. Framework (Domain, State, Actor). It is a
self-contained unit of domain knowledge, behavioural constraints, and processing tools that
brings a specific subject area — education, agriculture, industrial operations, system
administration — into the Lumina engine as a bounded authority.

The word *bounded* is deliberate. A domain pack does not integrate loosely with the engine;
it declares a closed cognitive sub-system that:

- owns its own **physics** — invariants, standing orders, escalation triggers
- owns its own **tools** — active verifiers for domain-specific propositions
- owns its own **information gate** — an NLP pre-interpreter that defines which signals matter
  in this domain and extracts them deterministically before any LLM inference happens
- owns its own **domain library** — passive state estimators tracking entity state across turns
- owns its own **synthesis layer** — a runtime adapter that computes the engine contract fields
- optionally owns its own **narrative framing** — a world-sim persona for human-facing contexts

The engine (`src/lumina/`) knows nothing about what a domain pack contains. It reads only
the two engine contract fields (`problem_solved`, `problem_status`) that the pack's runtime
adapter emits. Every domain-specific field name, vocabulary term, and computation lives
entirely inside the pack. This is the **self-containment contract** (see §E).

---

## B. The Seven Components

Every domain pack is composed of up to seven components. Not all are required for a minimal
pack, but all seven are present in a fully-realised production pack.

| Component | Location | Who calls it | Mandatory | What it owns |
|---|---|---|---|---|
| **Physics files** | `modules/<module>/domain-physics.yaml` and `.json` | Core engine at session load | Yes | Invariants (critical/warning), standing orders, escalation triggers, artifact definitions |
| **Tool adapters** | `modules/<module>/tool-adapters/*.yaml` + `controllers/tool_adapters.py` | Orchestrator policy system (YAML-declared) or runtime adapter directly (Python) | Recommended | Active, deterministic verifiers — compute domain-specific field values on demand |
| **Runtime adapter** | `controllers/runtime_adapters.py` | Core engine on every turn | Yes | Phase A (NLP pre-processing before LLM) + Phase B (signal synthesis after tools); emits engine contract fields |
| **NLP pre-interpreter** | `controllers/nlp_pre_interpreter.py` | Core engine before LLM prompt assembly | Yes (all text-input domains) | Deterministic extraction of domain-meaningful signals from raw input; produces `_nlp_anchors` |
| **Domain library** | `domain-lib/reference/*.md` specs + `controllers/*.py` implementations | Runtime adapter only — never the engine directly | Where applicable | Passive reference specs (interpretation schemas, estimator definitions) and state estimators tracking entity state across turns (ZPD monitor, fluency tracker, fatigue model) |
| **Group Libraries / Group Tools** | `domain-lib/*.py` (libraries) + `controllers/group_tool_adapters.py` (tools) | Runtime adapter (libraries) or policy system (tools) — declared in physics files | Where applicable | Shared pure-function libraries and shared active verifiers used by multiple modules within the domain |
| **World-sim (optional)** | `world-sim/*.md` + `world-sim/templates.yaml` | Runtime adapter, once at session start | No | Narrative framing layer — cosmetic only; domain physics and invariants are unchanged inside any world-sim theme |

These components are not interchangeable and must not be substituted for one another. The
tool adapters verify; the domain library estimates; the runtime adapter synthesises; the NLP
pre-interpreter gates. Confusing these responsibilities is the most common mistake when
authoring a new domain pack.

---

## C. The Information Gate — Why NLP Runs First

The NLP pre-interpreter is not an optional quality-of-life enhancement. It is the domain's
**information gate** — the domain's assertion that *it defines which signals are meaningful
in this context, and those signals will be extracted with certainty before any probabilistic
LLM inference begins*.

### The rationale

An LLM receiving raw unstructured text will compute its own implicit representations of
that text. If the domain has authoritative prior knowledge about what matters — "in an algebra
session, whether the student's answer is numerically correct is a deterministic fact, not an
inference" — that knowledge must be asserted before the LLM constructs its interpretation.
Otherwise the LLM's representation may diverge from the domain's authoritative view, and
there is no mechanism to detect or correct that divergence.

This is the core reliability contribution of Phase A:

> **Determinism must precede probability.** Anything that can be extracted with certainty
> must be extracted before the uncertain reasoning begins.

The NLP pre-interpreter runs first, produces structured signals, and injects them as
`_nlp_anchors` into the LLM context — explicitly tagged as deterministic. The LLM may
override them; the anchors are priors, not hard constraints at the LLM layer. But given a
deterministic prior, overriding it becomes the exception rather than the rule. Without it,
the LLM is guessing at information the domain already knows.

### What the pre-interpreter produces

The pre-interpreter's entry point (`nlp_preprocess(input_text, task_context) -> dict`)
returns a dict containing:

- Zero or more domain-specific evidence fields (e.g., `correctness`, `extracted_answer`,
  `intent_type`)
- A `_nlp_anchors` list: structured records of each extracted signal, each with `field`,
  `value`, `confidence`, and an optional `detail` string

The anchors are formatted by the runtime adapter into the LLM context hint:

```
NLP pre-analysis (deterministic):
- correctness: correct (confidence: 0.95) — matched answer "4" to expected "x = 4"
- frustration_marker_count: 0
- off_task_ratio: 0.1
Use these as starting values. Override if your analysis disagrees.
```

### Each domain owns its own gate

The NLP pre-interpreter is intentionally per-domain, not shared. The signals meaningful in
an algebra education session (answer correctness, frustration markers, hint requests,
off-task ratio) are entirely different from those meaningful in a system administration
session (mutation vs read intent, target user, target role, compound command detection).
There is no universal pre-interpreter, and there should not be one.

This design ensures that domain boundary violations are structurally impossible at the NLP
layer: a student message cannot accidentally activate system administration signal
extraction, because the pre-interpreter loaded at session start is the education domain's —
registered in `cfg/runtime-config.yaml` as the `nlp_pre_interpreter` adapter for that
session's domain.

For the full two-tier architecture (system-level domain classification → domain NLP
pre-interpreter), see [`nlp-semantic-router(7)`](nlp-semantic-router.md). For the Phase A
implementation contract, anchor injection format, and extractor reference for the education
domain, see [`domain-adapter-pattern(7)`](domain-adapter-pattern.md) §D.

---

## D. Physics as Standing Orders

A common misreading of domain packs is that the domain physics file *controls* or *executes*
domain behaviour — that declaring an invariant is the same as enforcing it. This is not how
physics files work.

The domain physics file is the domain's **law**, not its **executor**. It declares:

- what must be true (**invariants**)
- what the orchestrator is authorised to do automatically when a constraint is triggered
  (**standing orders**)
- what conditions require Meta Authority intervention (**escalation triggers**)

The orchestrator reads these declarations and decides whether to act on them in the current
context. Physics alone triggers nothing.

### Invariant severity levels

| Severity | Meaning | Automatic response |
|---|---|---|
| `critical` | Violation halts autonomous action | Immediate standing order execution or escalation to Meta Authority |
| `warning` | Violation approaches a defined threshold | Standing order response within the current session; no halt |

### Standing orders are bounded permissions, not scripts

A standing order specifies what the orchestrator *may* do in response to an invariant
condition, bounded by explicit parameters. It is a permission with constraints, not an
execution script. The orchestrator evaluates whether the standing order applies to the
current turn before acting.

**Education domain example:**

```yaml
id: reduce_challenge_on_exhaustion
trigger: max_attempts.attempts_remaining == 0
action: reduce_challenge_tier
parameters:
  reduction_amount: 1
  notify_subject: true
```

This authorises the orchestrator to reduce the challenge tier when attempts are exhausted.
It does not specify the new problem content — that remains a proposal subject to invariant
checking, not an automatic bypass of the normal proposal-validation pipeline.

### Hash commitment

Before a domain physics file becomes active in a session, its hash is committed to the
System Log. This ensures the invariant set cannot change mid-session without an explicit log
record. Any version change to `domain-physics.json` requires a new hash commitment and a
`CHANGELOG.md` entry with a semver increment.

For the physics file's role within the three-stage proposal pipeline (Proposal →
Validation → HITL), and how standing orders interact with the execution gate, see
[`command-execution-pipeline(7)`](command-execution-pipeline.md).

### The SOP / TM / Glossary Mental Model

The three knowledge layers of a domain pack map to a military / institutional mental model
that clarifies who declares *what* the rules are, who declares *how* to execute them, and
who keeps the shared vocabulary aligned:

| Layer | Analogy | Location | Purpose |
|---|---|---|---|
| **Physics files** | **Standing Operating Procedures (SOPs)** | `modules/<module>/domain-physics.yaml` | Declare *what must be true* — invariants, standing orders, escalation triggers. The domain's law. |
| **Domain library** | **Technical Manuals (TMs)** | `domain-lib/reference/*.md` + `controllers/*.py` | Declare *how to do what is being asked* — interpretation schemas, field extraction rules, command disambiguation specs, step-by-step execution guidance. The tools and procedures. |
| **Glossary** | **Cross-reference index** | `glossary` section in domain-physics | Define shared vocabulary so that every component — physics, TMs, NLP pre-interpreter, SLM prompts — uses the same term for the same concept. |

SOPs tell the orchestrator what constraints exist. TMs tell the runtime adapter and SLM how
to interpret inputs, classify turns, and execute operations within those constraints.
The glossary ensures the vocabulary used in SOPs and TMs is unambiguous.

This separation is deliberate: physics files should never contain execution logic or
step-by-step procedures, and domain-lib specs should never declare invariants or escalation
triggers. When authoring a domain pack, the test is simple:

- If it says *"this must be true"* → physics (SOP)
- If it says *"here is how to do X"* → domain-lib (TM)
- If it says *"term Y means Z"* → glossary (cross-reference)

---

## E. The Self-Containment Contract

The self-containment contract is the hard rule that makes domain isolation enforceable and
domain adding zero-impact on the engine:

> **Zero domain-specific names may appear in `src/lumina/`.**

All domain logic, domain field names, domain computations, and domain vocabulary live
exclusively inside the domain pack. The core engine never references `correctness`,
`frustration_marker_count`, `intent_type`, `moisture_level`, or any other domain-specific
name. It reads only `problem_solved` and `problem_status` from the evidence dict returned
by the runtime adapter.

This is what makes it possible to add a new domain pack — radiology, autonomous vehicle
telemetry, industrial process control — without any changes to the engine. The engine will
load the new pack's runtime adapter, call `interpret_turn_input()`, and read the two
contract fields from the returned evidence dict. It does not need to know what the evidence
dict contains beyond those two fields.

### The closed information channel

Each domain pack is a closed information channel. The domain controls what enters and what
exits; the engine observes only the exit:

```
raw input
    │
    ▼
NLP pre-interpreter — domain-owned, pure regex/keyword, no LLM
    │
    ▼
LLM prompt assembly — NLP anchors injected into context
    │
    ▼
LLM inference
    │
    ▼
tool adapters + domain library — domain-owned
    │
    ▼
runtime adapter synthesis — assembles evidence dict
    │
    ▼
engine reads: problem_solved, problem_status
```

At no point does the engine inspect the intermediate stages. Domain-specific field names
travel through the channel but never cross the domain boundary into engine code.

For the engine contract field reference, types, defaults, and worked examples across
education and hypothetical scientific domains, see [`domain-adapter-pattern(7)`](domain-adapter-pattern.md) §B.

---

## F. Cross-Domain Comparison

The domain pack pattern is universal. What varies between packs is content, not structure.
The three currently active domain packs illustrate this:

| Dimension | `education` | `system` | `agriculture` |
|---|---|---|---|
| **Pre-interpreter extractors** | answer_match, frustration_markers, hint_request, off_task_ratio | admin_verb (mutation/read), target_user, target_role, compound_command, glossary_match | soil sensor thresholds, pest signal keywords, moisture anomaly detection |
| **Physics invariant type** | Pedagogical (max_consecutive_incorrect, zpd_drift_limit, session_fatigue) | Operational security (privilege escalation gates, unauthorised access paths) | Environmental (moisture_low, pest_pressure_critical, yield_at_risk) |
| **Tool adapters** | algebra-parser, substitution-checker, calculator | system ctl tools | operations tool adapters |
| **Domain library components** | ZPD monitor, fluency tracker, fatigue estimator | Turn interpretation spec, command interpreter spec, sensor probes | Turn interpretation spec, sensor normalisation |
| **World-sim enabled** | Yes (space, nature, sports, general_math themes) | No | No |
| **Access roles** | user, domain_authority, it_support, qa, root | it_support, root | domain-specific |
| **LLM vs SLM routing** | LLM (external permitted) | SLM-only (`local_only: true`) | LLM (external permitted) |
| **Module structure** | Multiple algebra modules; module_map routes by student domain_id | Single system-core module | Single operations-level-1 module |

The system domain's `local_only: true` is a security boundary, not an architectural
exception — it reflects the domain's threat model (no operator command should leave the
trust boundary). Every other structural pattern is identical across all three packs.

The absence of a domain library in the system and agriculture packs is not a deficiency;
those domains have no multi-turn entity state to track at the depth education requires.
Every domain pack includes exactly as much structure as its subject area demands.

---

## G. Quick Reference — File Layout

The canonical domain pack directory layout. Pack-level items apply to the whole domain;
module-level items apply to one specific subject area (algebra-level-1, operations-level-1,
system-core, etc.) within the domain.

```
domain-packs/{domain}/
│
├── README.md                          # Pack overview and authoring notes
│
├── cfg/
│   └── runtime-config.yaml           # PACK-LEVEL — adapter registration, access control,
│                                     #   module_map routing, world-sim config,
│                                     #   slm_weight_overrides, deterministic_templates
│
├── modules/
│   └── {module}/                     # MODULE-LEVEL — one directory per subject area
│       ├── domain-physics.yaml       #   Human-authored (source of truth)
│       ├── domain-physics.json       #   Machine-authoritative (derived from YAML)
│       ├── evidence-schema.json      #   Domain vocabulary for this module's evidence dict
│       ├── prompt-contract-schema.json  # Domain-specific prompt constraint extensions
│       ├── {entity}-profile-template.yaml  # Initial entity state template
│       └── tool-adapters/
│           └── {tool}-adapter-v1.yaml   # One file per active verifier (YAML-declared policy tools)
│
├── controllers/                      # PACK-LEVEL — Python implementations shared across modules
│   ├── nlp_pre_interpreter.py        # Phase A information gate  (exported: nlp_preprocess)
│   ├── runtime_adapters.py           # Phase A + B synthesis     (exported: interpret_turn_input)
│   └── tool_adapters.py              # Direct tool callables for read-only retrieval
│
├── docs/                             # PACK-LEVEL — domain-scoped man pages (mirrors root docs/)
│   ├── README.md                     #   Section index for this domain's documentation
│   ├── 1-commands/                   #   REQUIRED — domain CLI / admin commands
│   │   └── README.md
│   ├── 3-functions/                  #   REQUIRED — domain-lib & controller function references
│   │   └── {function}.md
│   ├── 7-concepts/                   #   REQUIRED — domain design rationale & architecture
│   │   └── README.md
│   ├── 2-syscalls/                   #   Optional — domain API endpoints
│   ├── 4-formats/                    #   Optional — domain data formats
│   ├── 5-standards/                  #   Optional — domain-specific conventions
│   ├── 6-examples/                   #   Optional — worked domain examples
│   └── 8-admin/                      #   Optional — domain admin operations
│
├── domain-lib/                       # PACK-LEVEL — passive reference specs + shared libraries
│   ├── README.md                     #   Directory contents and component descriptions
│   ├── reference/                    #   Interpretation schemas and domain knowledge specs (TMs)
│   │   ├── turn-interpretation-spec-v1.md    # Turn-level field extraction schema
│   │   └── {domain-specific}-spec-v1.md      # Additional spec files per domain
│   ├── sensors/                      #   Sensor and telemetry modules (where applicable)
│   │   └── {sensor_module}.py
│   ├── {group_library}.py            #   Group Library — shared pure-function module (see §B)
│   └── (estimator implementations live in controllers/)
│
├── prompts/                          # PACK-LEVEL — persona directives ONLY
│   └── domain-persona-v1.md          #   Domain voice and identity ("how to talk")
│
└── world-sim/                        # PACK-LEVEL — optional narrative framing (omit if unused)
    ├── world-sim-spec-v1.md
    ├── magic-circle-consent-v1.md
    ├── artifact-and-mastery-spec-v1.md
    └── world-sim-templates.yaml
```

### Prompts vs Domain Library — "How to Talk" vs "What to Know"

The `prompts/` and `domain-lib/reference/` directories serve fundamentally different roles:

| Directory | Analogy | Contains | Consumed by |
|-----------|---------|----------|-------------|
| `prompts/` | **Voice** — persona directives | `domain-persona-v1.md` — the CI's tone, vocabulary, and identity | Persona builder at session start |
| `domain-lib/reference/` | **Knowledge** — Tech Manuals | Interpretation schemas, field extraction rules, command disambiguation specs | Runtime adapter and SLM on every turn; physics files reference these as group libraries |

Persona directives tell the CI *how to talk*. Reference specs tell it *what to know*. This
distinction is enforced by convention: `prompts/` contains no interpretation logic, and
`domain-lib/reference/` contains no voice or identity directives.

`cfg/runtime-config.yaml` is the pack's manifest to the engine: it registers adapters,
declares access control, maps entity domain IDs to module physics paths, and enables
world-sim features. The engine reads this file at session initialisation and wires up the
pack's components — no engine code changes are required to add a new domain pack.

For authoring a new domain pack from scratch (8-step authoring process), see
`domain-packs/README.md`. For the engine contract field reference, Phase A/B implementation
contract, and three-layer component distinction in depth, see
[`domain-adapter-pattern(7)`](domain-adapter-pattern.md).

---

## H. Domain Pack `/docs` — Unix Man-Page Sections

Every domain pack should include a `/docs` directory that mirrors the root `docs/` man-page
section layout (1–8). This makes domain documentation structurally identical to system
documentation, enabling a single indexing pipeline (MiniLM housekeeper, MANIFEST integrity,
retrieval index) to walk any `/docs` tree — root or domain — without special-casing.

### Required sections

| Section | Purpose | Must contain at minimum |
|---|---|---|
| `1-commands/` | Domain-scoped CLI commands, admin verbs, operator actions | `README.md` |
| `3-functions/` | Function-level references for domain-lib components, controllers, NLP extractors | At least one `{function}.md` per exported controller function |
| `7-concepts/` | Architectural rationale, design decisions, domain theory | `README.md` |

### Optional sections

| Section | Include when |
|---|---|
| `2-syscalls/` | The domain exposes its own API endpoints |
| `4-formats/` | The domain defines wire formats, evidence schemas, or file layouts beyond what physics files cover |
| `5-standards/` | The domain defines naming or authoring conventions beyond lumina-core and domain-physics |
| `6-examples/` | Worked examples, trace walkthroughs, or sample sessions |
| `8-admin/` | Domain-specific administration procedures (role setup, physics editing, escalation handling) |

### Man-page formatting

Each document follows the same heading conventions as root docs:

```markdown
# {name}({section})

## NAME
## SYNOPSIS
## DESCRIPTION
## SEE ALSO
```

Where `{section}` is the numeric man section (1, 3, 7, etc.). This consistent structure
enables automated chunking by `## ` headers for embedding pipelines.

---

## SEE ALSO

- [`domain-adapter-pattern(7)`](domain-adapter-pattern.md) — three-layer distinction and Phase A/B lifecycle
- [`group-libraries-and-tools(7)`](group-libraries-and-tools.md) — Group Libraries and Group Tools: shared resources within a domain pack
- [`edge-vectorization(7)`](edge-vectorization.md) — per-domain vector stores and rebuild triggers
- [`execution-route-compilation(7)`](execution-route-compilation.md) — ahead-of-time compilation of physics execution routes
- [`nlp-semantic-router(7)`](nlp-semantic-router.md) — two-tier NLP architecture and domain classification

### Integrity tracking

Domain-pack doc files are tracked in the root `docs/MANIFEST.yaml` under their full
relative paths (e.g., `domain-packs/education/docs/3-functions/fluency-monitor.md`). The
standard `manifest_integrity regen` and `check` subcommands cover domain-pack docs alongside
system docs. New domain-pack doc files are automatically discovered by `manifest_integrity
discover`.
