# System Domain Pack — Project Lumina

**Version:** 1.0.0  
**Status:** Active  
**Access:** `root` and `super_admin` roles only

---

The system domain pack (`domain-packs/system/`) provides Lumina's internal administration session interface.  It is the default routing destination for `root` and `super_admin` users when no explicit `domain_id` is given in a request and NLP routing does not confidently match another domain.

## Structure

```
domain-packs/system/
  cfg/
    runtime-config.yaml          — Full runtime config (replaces cfg/system-runtime-config.yaml stub)
  modules/
    system-core/
      domain-physics.json        — System core domain physics (glossary, permissions, topics)
      operator-profile.yaml      — Default operator entity profile template
  prompts/
    domain-system-override.md   — System-domain LLM persona and rendering rules
    turn-interpretation.md      — Turn classification prompt (query_type, target_component)
  controllers/
    runtime_adapters.py         — Minimal adapters: build_system_state, system_domain_step, interpret_turn_input
```

## Access Control

Session execution is restricted to principals with `root` or `super_admin` roles.  The domain-physics permission block uses mode `"770"` — owner/group have full rwx, all others have no access.  Regular `user`, `operator`, `half_operator`, and `admin` principals who attempt to chat in the system domain will receive a `403 Module access denied` response.

## Role-Based Default Routing

See `cfg/domain-registry.yaml` (`role_defaults`) and `src/lumina/core/domain_registry.py` (`resolve_default_for_user`).  The global `default_domain: education` is intentionally kept to mask system internals from domain-level users.

## What system domain sessions support

- **Glossary queries** — explain any term in the system-core domain physics glossary
- **Status queries** — discuss the state of a Lumina component as reported in session context
- **Diagnostic discussion** — describe a problem and receive structured troubleshooting guidance
- **Config review** — walk through domain-registry, domain-physics, or system-physics structure
- **Operational monitoring** — System Log record structure, daemon batch status, hash-chain integrity

The system domain does **not** support:
- World-sim / persona themes (explicitly disabled in persona rules)
- Learning-state or ZPD tracking (no learner model)
- Tool adapters beyond what core Lumina provides
