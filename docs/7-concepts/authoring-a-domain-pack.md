---
title: Authoring a Domain Pack
version: 1.0.0
last_updated: 2026-04-17
category: concept
tags: [domain-pack, authoring, template, tutorial]
---

# Authoring a Domain Pack

A domain pack is a self-contained directory under `model-packs/` that
teaches Lumina how to operate in a specific knowledge domain.  Domain
packs are the primary extension mechanism — they define the rules
(invariants), automated responses (standing orders), escalation policy,
entity profiles, and runtime adapters that shape every conversation.

This guide walks you through creating a new domain pack from the
`model-packs/template/` scaffold.

---

## Prerequisites

- A working Lumina development environment (`pip install -r requirements-dev.txt`)
- Familiarity with the D.S.A. framework (Domain / State / Actor) — see
  `docs/7-concepts/dsa-framework.md`
- A clear idea of your domain's rules and who the entities (actors) are

---

## Step 1: Copy the Template

```bash
cp -r model-packs/template model-packs/my-domain
```

Then do a global find-and-replace:

| Find | Replace with | Where |
|------|-------------|-------|
| `template` | `my-domain` | Directory names, `pack_id`, all file paths |
| `tmpl` | `mydom` | Module ID short codes (`domain/tmpl/...` → `domain/mydom/...`) |
| `example-module` | Your first module name | Everywhere |
| `example-task-001` | Your first task ID | `runtime-config.yaml` |

---

## Step 2: Define Your Domain Physics

The **domain physics** file is the most important file in your domain.  It
declares the invariants (rules) the orchestrator checks every turn, the
standing orders (bounded automated responses), and the escalation triggers
(when to hand off to a human).

Edit `modules/<your-module>/domain-physics.yaml`:

### 2a. Invariants

Every domain needs at least one invariant.  Invariants come in two severities:

- **critical** — halts all autonomous action; may trigger immediate escalation.
- **warning** — triggers a standing order (bounded automated response).

```yaml
invariants:
  - id: measurement_out_of_range
    description: "Sensor reading exceeds safe operating limits."
    severity: critical
    check: "reading > max_safe_value"
    standing_order_on_violation: halt_and_escalate
```

The `check` field is a predicate expression evaluated against the evidence
dict (the output of your turn interpreter).  Use field names that match
your `turn_input_schema`.

For complex invariants that require subsystem logic (e.g. drift detection
over a sliding window), use `handled_by` to delegate to a named subsystem:

```yaml
  - id: trend_drift
    description: "Metric trending outside acceptable band over recent window."
    severity: warning
    handled_by: my_trend_monitor
    standing_order_on_violation: request_more_detail
```

### 2b. Standing Orders

Each invariant violation triggers a standing order — a bounded automated
response with a retry cap:

```yaml
standing_orders:
  - id: request_more_detail
    action: request_more_detail
    trigger_condition: "measurement_out_of_range"
    max_attempts: 2
    escalation_on_exhaust: true
    description: "Ask the entity to clarify or provide more data."
```

When `max_attempts` is exhausted and `escalation_on_exhaust` is true,
the system fires the escalation chain.

### 2c. Escalation Triggers

Define who gets notified when things go wrong:

```yaml
escalation_triggers:
  - id: unresolved_violation
    condition: "Standing order exhausted without resolution."
    target_role: admin
    sla_minutes: 30
```

### 2d. Generate JSON

The runtime loads `.json`, not `.yaml`.  After editing, convert:

```bash
python -c "import yaml, json, sys; \
  json.dump(yaml.safe_load(open(sys.argv[1])), \
  open(sys.argv[1].replace('.yaml','.json'),'w'), indent=2)" \
  model-packs/my-domain/modules/my-module/domain-physics.yaml
```

Validate against the schema:

```bash
python -m pytest tests/ -k "test_domain_physics_schema" -v
```

---

## Step 3: Implement the Three Required Adapters

Every domain pack must export three callables in `controllers/runtime_adapters.py`:

### 3a. `build_initial_state(profile) → dict`

Called once at session start.  Reads the entity profile and returns the
initial session state dict.  This becomes the `state` argument to every
subsequent `domain_step` call.

```python
def build_initial_state(profile: dict) -> dict:
    return {
        "score": 0.0,
        "uncertainty": 0.5,
        "turn_count": 0,
    }
```

### 3b. `domain_step(state, task_spec, evidence, params) → (new_state, decision)`

The heart of your domain.  Called every turn after evidence is produced.
Updates the session state and returns a decision dict the orchestrator
uses for action selection.

The decision dict standard keys:
- `tier`: `"ok"` | `"minor"` | `"major"` | `"critical"`
- `action`: standing-order action name, or `None`
- `frustration`: `bool`
- `escalation_eligible`: `bool` (set `False` during baseline priming —
  see `docs/7-concepts/baseline-before-escalation.md`)

### 3c. `interpret_turn_input(call_llm, input_text, task_context, prompt_text, default_fields, tool_fns) → dict`

Calls the LLM with your turn interpretation prompt and parses the JSON
response into an evidence dict.  Merge `default_fields` for any missing
keys.  Optionally call deterministic tools from `tool_fns` to override
SLM estimates with ground-truth values.

---

## Step 4: Configure the Runtime

Edit `cfg/runtime-config.yaml`.  The critical sections:

| Section | Purpose |
|---------|---------|
| `domain_system_prompt_path` | Points to your persona prompt |
| `turn_interpretation_prompt_path` | Points to your turn interpretation spec |
| `domain_physics_path` | Default module's physics file |
| `subject_profile_path` | Default entity profile |
| `default_task_spec` | Fallback task when no module override exists |
| `module_map` | Per-module configuration overrides |
| `adapters` | Binds the 3 required callables |
| `turn_input_schema` | Documents your evidence fields |
| `turn_input_defaults` | Fallback values for missing SLM fields |
| `ui_manifest` | Frontend branding and consent |

### Module Map

Each module gets an entry in `module_map` with a fully-qualified ID:

```yaml
module_map:
  domain/mydom/my-module/v1:
    domain_physics_path: model-packs/my-domain/modules/my-module/domain-physics.json
    initial_module_state:
      score: 0.0
    adapters:
      # Override the default adapters for this specific module:
      domain_step:
        module_path: model-packs/my-domain/controllers/custom_adapters.py
        callable: custom_domain_step
```

---

## Step 5: Define the Persona Prompt

Edit `prompts/domain-persona-v1.md`.  Key sections:

- **target_audience** — who the entity is
- **tone_profile** — how the LLM should communicate
- **forbidden_disclosures** — internal values the LLM must never reveal
- **rendering_rules** — one rule per `prompt_type` your standing orders produce
- **persona_rules** — narrative framing, branding, safety guardrails

---

## Step 6: Write the Turn Interpretation Spec

Edit `domain-lib/reference/turn-interpretation-spec-v1.md`.  This is the
system prompt sent to the SLM for every turn.  It must:

1. Define the exact JSON schema the SLM must output
2. Explain each field and its valid values
3. Provide domain-specific grounding rules
4. Match the field names in `turn_input_schema` and `turn_input_defaults`

---

## Step 7: Set Up Entity Profiles

Edit `profiles/entity.yaml` (Layer 3) and `cfg/domain-profile-extension.yaml`
(Layer 2).  The runtime merges profiles:

```
base-entity-profile.yaml (Layer 1 — system)
  ↓ merged with
domain-profile-extension.yaml (Layer 2 — your domain)
  ↓ merged with
entity.yaml (Layer 3 — role-specific)
```

Add one profile YAML per domain role if needed.

---

## Step 8: Add Phase A Extractors (Recommended)

Edit `controllers/nlp_pre_interpreter.py`.  Phase A runs deterministic
pattern extractors before the LLM turn interpreter.  Use it for:

- Safety-critical fields (don't rely solely on the SLM)
- Structured inputs that can be reliably regex'd
- Domain-specific codes, IDs, measurements

The extractors' output overrides SLM estimates when both produce the
same field.

---

## Step 9: Register the Domain

Add your domain to the domain registry so the runtime can discover it.
See `cfg/domain-registry.yaml` for the format.

---

## Step 10: Validate

```bash
# Validate domain-physics.json against the schema
python -m pytest tests/ -k "domain_physics" -v

# Run the template pack smoke test (adapt for your domain)
python -m pytest tests/test_template_pack.py -v

# Full suite — confirm no regressions
python -m pytest tests/ -x -q
```

---

## Common Patterns

### Operations Dispatcher (Slash Commands)

If your domain needs slash commands (e.g. `/assign`, `/status`), use the
ops dispatcher pattern from `controllers/template_operations.py`:

1. Create handler functions in `controllers/ops/` submodules
2. Import them in the dispatcher and add to `_HANDLERS`
3. Wire the dispatcher in `runtime-config.yaml` as `operation_handlers`

### Baseline Before Escalation

If your domain has subsystems that need a priming period (e.g. drift
detection with a sliding window), use the baseline-before-escalation
pattern:

- Set `escalation_eligible: False` in your `domain_step` decision dict
  while the baseline is priming
- The framework suppresses metric-driven escalation until you signal ready
- See `docs/7-concepts/baseline-before-escalation.md`

### Deterministic Tool Overrides

In `interpret_turn_input`, use `tool_fns` to call deterministic tools
that override SLM estimates with ground truth:

```python
checker = (tool_fns or {}).get("my_checker")
if checker:
    result = checker({"input_text": input_text, "evidence": evidence})
    if isinstance(result, dict) and "on_track" in result:
        evidence["on_track"] = result["on_track"]
```

### World-Sim / Narrative Framing

For domains that benefit from narrative framing (games, training
scenarios), add a `world-sim/` directory with theme definitions and
reference the themes in your persona prompt's `persona_rules`.

---

## Troubleshooting

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| Runtime loader rejects the pack | Missing required config key or adapter | Check the 5 required keys and 3 required adapters in runtime-config.yaml |
| Domain physics validation fails | JSON doesn't match schema | Regenerate JSON from YAML; check against `standards/domain-physics-schema-v1.json` |
| SLM returns garbage evidence | Turn interpretation spec unclear | Add explicit examples and constraints to the spec |
| Escalation fires too early | No baseline priming | Add `escalation_eligible: False` during warmup |
| Standing order loops | `max_attempts` too high or condition never clears | Review your `domain_step` — make sure state progresses |
