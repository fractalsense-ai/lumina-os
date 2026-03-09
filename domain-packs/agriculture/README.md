# Agriculture Domain Pack

**Status:** Experimental / partial implementation

---

This directory contains early agriculture-domain assets used to test runtime decoupling.

Implemented today:
- `modules/operations-level-1/domain-physics.json`
- `runtime-config.yaml`
- prompt overrides under `prompts/`
- adapter stub under `reference-implementations/`

Not yet complete:
- no full `modules/operations-level-1` profile/template set
- no production-ready tool adapter implementations
- no domain-lib specs equivalent to the education pack
- no validated end-to-end test scenarios

Current structure:

```
agriculture/
├── README.md
├── runtime-config.yaml
├── modules/
│   └── operations-level-1/
│   ├── domain-physics.json
│   ├── example-subject.yaml
│   └── tool-adapters/
│       └── collar-sensor-adapter-v1.yaml
├── prompts/
│   ├── domain-system-override.md
│   └── turn-interpretation.md
└── reference-implementations/
    └── runtime-adapters.py
```

Use this pack as an experimental reference, not as a fully validated production domain.

For authoring guidance, see [`../README.md`](../README.md) and [`../../specs/domain-profile-spec-v1.md`](../../specs/domain-profile-spec-v1.md).
