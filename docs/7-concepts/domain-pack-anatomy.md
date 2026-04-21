---
version: 1.4.0
last_updated: 2026-04-12
---

# Domain Pack Anatomy

**Version:** 1.4.0  
**Status:** Active  
**Last updated:** 2026-04-12  

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

## B. The Eight Components

Every domain pack is composed of up to nine components. Not all are required for a minimal
pack, but all nine are present in a fully-realised production pack.

| Component | Location | Who calls it | Mandatory | What it owns |
|---|---|---|---|---|
| **Physics files** | `modules/<module>/domain-physics.yaml` and `.json` | Core engine at session load | Yes | Invariants (critical/warning), standing orders, escalation triggers, artifact definitions |
| **Tool adapters** | `modules/<module>/tool-adapters/*.yaml` + `controllers/tool_adapters.py` | Orchestrator policy system (YAML-declared) or runtime adapter directly (Python) | Recommended | Active, deterministic verifiers — compute domain-specific field values on demand |
| **Runtime adapter** | `controllers/runtime_adapters.py` | Core engine on every turn | Yes | Phase A (NLP pre-processing before LLM) + Phase B (signal synthesis after tools); emits engine contract fields |
| **NLP pre-interpreter** | `controllers/nlp_pre_interpreter.py` | Core engine before LLM prompt assembly | Yes (all text-input domains) | Deterministic extraction of domain-meaningful signals from raw input; produces `_nlp_anchors` |
| **Domain library** | `domain-lib/reference/*.md` specs + `controllers/*.py` implementations | Runtime adapter only — never the engine directly | Where applicable | Passive reference specs (interpretation schemas, estimator definitions) and state estimators tracking entity state across turns (ZPD monitor, fluency tracker, fatigue model) |
| **Group Libraries / Group Tools** | `domain-lib/*.py` (libraries) + `controllers/group_tool_adapters.py` (tools) | Runtime adapter (libraries) or policy system (tools) — declared in physics files | Where applicable | Shared pure-function libraries and shared active verifiers used by multiple modules within the domain |
| **API route handlers** | `controllers/api_handlers.py` + `cfg/runtime-config.yaml` §adapters.api_routes | Core server at startup (dynamically mounted) | No | Domain-owned HTTP endpoints — telemetry submission, dashboard data, domain-specific queries. The core server wraps each handler with auth + role enforcement; the domain handler stays framework-free |
| **Frontend plugin** | `web/plugin.ts` + `web/components/` + `web/services/` | Framework `PluginRegistry` at UI load time | No | Domain-owned UI: dashboard tabs, sidebar panels, slash commands, chat hooks, client-side services. Built as ES module via Vite; declared in `cfg/runtime-config.yaml` §ui |
| **World-sim (optional)** | `world-sim/*.md` + `world-sim/templates.yaml` | Runtime adapter, once at session start | No | Narrative framing layer — cosmetic only; domain physics and invariants are unchanged inside any world-sim theme |

These components are not interchangeable and must not be substituted for one another. The
tool adapters verify; the domain library estimates; the runtime adapter synthesises; the NLP
pre-interpreter gates. Confusing these responsibilities is the most common mistake when
authoring a new domain pack.

### Interpreter pairing by module type

A single domain pack may contain modules of different *types*: learning modules (algebra,
pre-algebra), free-form modules (Student Commons), governance modules (domain-authority,
teacher, TA, guardian). Each type requires a paired **turn interpreter** and **domain
step** that match its pedagogical mode.

| Module type | Turn interpreter | Domain step | Tool usage mode |
|---|---|---|---|
| **Learning** | `interpret_turn_input` — builds algebra context hints, calls `algebra_parser` proactively 7×, produces `correctness`, `step_count`, `equivalence_preserved` | `domain_step` — ZPD monitor + fluency tracker | **Evaluation** (proactive): tools fire on every turn to verify student work |
| **Free-form** | `freeform_interpret_turn_input` — SLM classification of intent, deterministic student-command detection, no proactive tool calls | `freeform_domain_step` — neutral passthrough, no monitoring | **Assistance** (on-demand): tools available through `apply_tool_call_policy()` when conversation needs them |
| **Governance** | `interpret_turn_input` (governance) — SLM classification of operator intent, structured command dispatch via `slm_parse_admin_command` | *(governance modules use the admin pipeline, not domain_step)* | **Command dispatch**: SLM parses operator commands into structured operation dicts |

**Rule:** When a module overrides `domain_step`, it MUST also override `turn_interpreter`.
The domain-level default adapters (registered in `cfg/runtime-config.yaml` §adapters) are
designed for the domain's primary learning modules. Non-learning modules that inherit the
learning turn interpreter will produce meaningless evidence (algebra scores applied to
journal entries, proactive parser calls with no equation context).

Module-level overrides are declared in the `module_map` entry:

```yaml
module_map:
  domain/edu/general-education/v1:
    adapters:
      domain_step:
        module_path: domain-packs/education/controllers/runtime_adapters.py
        callable: freeform_domain_step
      turn_interpreter:
        module_path: domain-packs/education/controllers/runtime_adapters.py
        callable: freeform_interpret_turn_input
    turn_interpretation_prompt_path: domain-packs/education/domain-lib/reference/freeform-turn-interpretation-spec-v1.md
```

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
| **Access roles** | user, admin, super_admin, operator, root | super_admin, root | domain-specific |
| **LLM vs SLM routing** | LLM (external permitted) | SLM-only (`local_only: true`) | LLM (external permitted) |
| **Module structure** | Multiple algebra modules; module_map routes by student domain_id | Single system-core module | Single operations-level-1 module |

The system domain's `local_only: true` is a security boundary, not an architectural
exception — it reflects the domain's threat model (no operator command should leave the
trust boundary). Every other structural pattern is identical across all three packs.

The absence of a domain library in the system and agriculture packs is not a deficiency;
those domains have no multi-turn entity state to track at the depth education requires.
Every domain pack includes exactly as much structure as its subject area demands.

---

## G. Slash Command Debugging Loop

Developing a domain pack involves constant iteration on operation handlers, HITL exemptions,
and role boundaries. The majority of this work is **deterministic** — it does not need a
running LLM or SLM. The debugging loop described here lets a developer validate the full
command pipeline from HTTP request to operation execution using only `pytest` and the
`TestClient`, with no external inference services.

### Why this works

The command dispatch pipeline (`_dispatch_command`) supports two entry modes:

1. **Natural-language** — requires an SLM to parse the instruction into a structured
   operation dict. This is the production path through the frontend chat box.
2. **Direct dispatch** — the caller supplies `operation` and `params` directly in the
   request body. The SLM is bypassed entirely.

Direct dispatch is the same code path the frontend's slash command parser uses: when a user
types `/assign TestStudent16`, the frontend resolves this to
`{ operation: "assign_student", params: { ... } }` and POSTs it to the appropriate tier
endpoint. No SLM is involved.

This means every domain-pack operation handler can be integration-tested end-to-end — from
HTTP request through RBAC gate, domain_id injection, HITL staging/exemption, and operation
execution — without any LLM or SLM dependency.

### The three-tier endpoint structure

Commands route through one of three endpoints based on the caller's required access level:

| Endpoint | Gate | Who can reach it |
|---|---|---|
| `POST /api/command` | Any authenticated user | Students, teachers, all roles |
| `POST /api/domain/command` | `admin`, `root`, `super_admin` | Domain administrators and above |
| `POST /api/admin/command` | `root`, `super_admin` | System-level operators only |

The frontend slash command registry (`src/web/services/slashCommands.ts`) assigns each
command a `tier` that maps to one of these endpoints via `tierEndpoint()`. When adding a new
operation handler to a domain pack, you must also decide its tier. The rule is simple:

- If any authenticated user should be able to invoke it → **user tier**
- If it requires domain governance authority → **domain tier**
- If it is a system-level mutation → **admin tier**

Per-operation `min_role` enforcement (declared in `runtime-config.yaml §operation_handlers`)
provides fine-grained RBAC within each tier. The endpoint gate is defence-in-depth; the
operation's `min_role` is the real access control.

### The inner loop

The recommended development cycle for a new operation handler:

```
1.  Declare the handler in runtime-config.yaml §operation_handlers
      → set callable, hitl_exempt, min_role

2.  Implement the handler in controllers/

3.  Write a direct-dispatch test:
      resp = client.post(
          "/api/command",                  # or /api/domain/command
          json={
              "operation": "my_new_op",
              "params": {"target": "x"},
          },
          headers={"Authorization": f"Bearer {token}"},
      )
      assert resp.status_code == 200

4.  Run: pytest tests/test_my_file.py::test_my_new_op -xvs

5.  Iterate on steps 1-4 until the handler works correctly.

6.  Add the slash command definition to slashCommands.ts
      → set name, operation, params mapping, tier

7.  Write tier-gate tests to verify RBAC boundaries:
      - user token → /api/domain/command → 403
      - DA token  → /api/admin/command  → 403
```

Steps 1–5 run in under a second per test. No server startup, no SLM, no LLM. The `TestClient`
from FastAPI/Starlette runs the ASGI app in-process with `NullPersistenceAdapter`, so there
is no database or filesystem setup either.

### What to test without an SLM

The deterministic parts of the pipeline that **should** be covered by direct-dispatch tests:

| Area | What to assert | Example |
|---|---|---|
| **Operation routing** | Known operation returns 200; unknown returns 422 | `"operation": "assign_student"` → 200 |
| **HITL exemption** | Exempt ops execute immediately (`staged_id: null`); non-exempt ops return a `staged_id` | `hitl_exempt: true` in runtime-config → `resp.json()["staged_id"] is None` |
| **Tier gate enforcement** | Wrong role at wrong endpoint returns 403 | User token at `/api/domain/command` → 403 |
| **min_role enforcement** | Operation rejects callers below its declared min_role | `min_role: admin` + user token → 403 |
| **domain_id injection** | `domain_id` from request body propagates into `params` | Send `"domain_id": "education"` in body, verify handler receives it |
| **Parameter normalisation** | `_normalize_slm_command` coerces types correctly | `governed_modules: "single"` → `["single"]` |
| **Handler return value** | The operation's result dict contains expected fields | `resp.json()["result"]["students"]` is a list |

### What still needs the SLM

Only two things require a live SLM:

1. **Natural-language parsing accuracy** — does the SLM correctly translate
   `"assign TestStudent16 to algebra"` into `{ operation: "assign_student", params: ... }`?
2. **Ambiguous instruction disambiguation** — does the SLM pick the right operation when
   the instruction is vague?

These are tested separately, typically with recorded fixtures or a small dedicated SLM test
suite. They should not block the inner development loop.

### Test fixture pattern

The standard test fixture for domain-pack operation testing:

```python
@pytest.fixture
def api_module(monkeypatch):
    monkeypatch.setenv(
        "LUMINA_RUNTIME_CONFIG_PATH",
        "domain-packs/education/cfg/runtime-config.yaml",
    )
    mod = _load_api_module()
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    return mod

@pytest.fixture
def client(api_module):
    return TestClient(api_module.app)
```

`BOOTSTRAP_MODE = True` auto-promotes the first registered user to root, giving you a
root token without external auth setup. Register additional users at lower roles to test
RBAC boundaries.

### Checklist for new domain-pack operations

When adding a new operation to a domain pack, verify all of the following pass before
considering the operation complete:

- [ ] Handler declared in `runtime-config.yaml §operation_handlers`
- [ ] `hitl_exempt` set correctly (true for read-only queries, false for mutations)
- [ ] `min_role` set to the least-privileged role that should invoke it
- [ ] Direct-dispatch integration test passes at the correct tier endpoint
- [ ] Tier-gate test confirms lower roles are rejected at higher-tier endpoints
- [ ] Slash command definition added to `slashCommands.ts` with correct tier
- [ ] `pytest -x -q` passes with no regressions

---

## H. Quick Reference — File Layout

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
│   ├── tool_adapters.py              # Direct tool callables for read-only retrieval
│   └── api_handlers.py              # Domain-owned API route handlers (optional; see §B)
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
declares access control, maps entity domain IDs to module physics paths, enables
world-sim features, and optionally declares `adapters.api_routes` — domain-owned HTTP
endpoints that the core server mounts at startup with auth/role wrappers (see §B, "API
route handlers"). The engine reads this file at session initialisation and wires up the
pack's components — no engine code changes are required to add a new domain pack.

For authoring a new domain pack from scratch (8-step authoring process), see
`domain-packs/README.md`. For the engine contract field reference, Phase A/B implementation
contract, and three-layer component distinction in depth, see
[`domain-adapter-pattern(7)`](domain-adapter-pattern.md).

---

## I. Domain Pack `/docs` — Unix Man-Page Sections

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
