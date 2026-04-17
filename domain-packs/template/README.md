# Template Domain Pack

A **copy-and-customise** scaffold for building new Lumina domain packs.

> **This is not a runnable domain.** It is a starter kit. Copy the entire
> `domain-packs/template/` directory to `domain-packs/<your-domain>/` and
> follow the TODO markers in each file.

---

## Quick Start

```bash
# 1. Copy the template
cp -r domain-packs/template domain-packs/my-domain

# 2. Global find-and-replace
#    "template" → "my-domain"     (directory names, pack_id, paths)
#    "tmpl"     → "mydom"         (module ID short code)
#    "example-module" → your first module name

# 3. Edit domain-physics.yaml with your invariants, standing orders,
#    and escalation triggers, then regenerate the JSON:
python -c "import yaml, json, sys; \
  json.dump(yaml.safe_load(open(sys.argv[1])), \
  open(sys.argv[1].replace('.yaml','.json'),'w'), indent=2)" \
  domain-packs/my-domain/modules/<module>/domain-physics.yaml

# 4. Implement your adapters in controllers/runtime_adapters.py

# 5. Register in the domain registry (see cfg/domain-registry.yaml)

# 6. Run the smoke test
python -m pytest tests/test_template_pack.py -v
```

---

## Directory Structure

```
template/
├── pack.yaml                          # Pack identity & HMVC layer map
├── CHANGELOG.md                       # Version history
├── README.md                          # This file
├── cfg/
│   ├── runtime-config.yaml            # Runtime configuration (START HERE)
│   └── domain-profile-extension.yaml  # Domain-wide profile fields (Layer 2)
├── controllers/
│   ├── runtime_adapters.py            # 3 required callables
│   ├── nlp_pre_interpreter.py         # Phase A deterministic extraction
│   ├── template_operations.py         # Ops dispatcher (slash commands)
│   └── ops/
│       ├── __init__.py
│       └── _helpers.py                # Guard/profile/commitment patterns
├── domain-lib/
│   └── reference/
│       └── turn-interpretation-spec-v1.md  # SLM output schema
├── modules/
│   └── example-module/
│       ├── domain-physics.yaml        # Human-editable physics source
│       ├── domain-physics.json        # Runtime physics (generated)
│       └── tool-adapters/
│           └── example-tool-adapter-v1.yaml
├── profiles/
│   └── entity.yaml                    # Default entity profile (Layer 3)
└── prompts/
    └── domain-persona-v1.md           # LLM persona prompt
```

---

## What Each File Does

| File | Purpose | Required? |
|------|---------|-----------|
| `pack.yaml` | Pack identity, module list, entry points | Yes |
| `cfg/runtime-config.yaml` | All runtime paths, adapters, module map, UI | Yes |
| `modules/*/domain-physics.json` | Invariants, standing orders, escalation rules | Yes |
| `profiles/entity.yaml` | Default entity profile | Yes |
| `controllers/runtime_adapters.py` | `build_initial_state`, `domain_step`, `interpret_turn_input` | Yes |
| `prompts/domain-persona-v1.md` | LLM persona definition | Yes |
| `domain-lib/reference/turn-interpretation-spec-v1.md` | Turn interpretation output schema | Yes |
| `cfg/domain-profile-extension.yaml` | Domain-wide profile fields | Recommended |
| `controllers/nlp_pre_interpreter.py` | Phase A deterministic extraction | Recommended |
| `controllers/template_operations.py` | Slash-command ops dispatcher | Optional |
| `controllers/ops/_helpers.py` | Shared guard/profile/commitment helpers | Optional |
| `modules/*/tool-adapters/*.yaml` | Tool adapter definitions | Optional |

---

## Customisation Checklist

- [ ] Rename directory from `template/` to your domain name
- [ ] Update `pack_id` in `pack.yaml`
- [ ] Update all paths in `cfg/runtime-config.yaml` (find-replace `template`)
- [ ] Define your invariants in `domain-physics.yaml`, regenerate `.json`
- [ ] Implement `build_initial_state` with your profile → state mapping
- [ ] Implement `domain_step` with your state transition logic
- [ ] Define your turn interpretation schema in `turn-interpretation-spec-v1.md`
- [ ] Customise the persona prompt in `prompts/domain-persona-v1.md`
- [ ] Add your entity profile fields in `profiles/entity.yaml`
- [ ] Add domain-wide fields in `cfg/domain-profile-extension.yaml`
- [ ] Define `turn_input_schema` and `turn_input_defaults` in runtime-config
- [ ] Set up `ui_manifest` branding (title, consent, theme, panels)
- [ ] Register in the domain registry
- [ ] Validate: `python -m pytest tests/test_template_pack.py -v`

---

## Further Reading

- [Authoring a Domain Pack](../../docs/7-concepts/authoring-a-domain-pack.md)
- [Domain Adapter Pattern](../../docs/7-concepts/domain-adapter-pattern.md)
- [HMVC Heritage](../../docs/7-concepts/hmvc-heritage.md)
- [Baseline Before Escalation](../../docs/7-concepts/baseline-before-escalation.md)
- [Command Execution Pipeline](../../docs/7-concepts/command-execution-pipeline.md)
