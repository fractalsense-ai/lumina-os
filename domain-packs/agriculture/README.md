# Agriculture Domain Pack

**Status:** Experimental / partial implementation

---

This directory contains early agriculture-domain assets used to test runtime decoupling.

Implemented today:
- `operations-level-1/domain-physics.json`
- `runtime-config.yaml`
- prompt overrides under `prompts/`
- adapter stub under `reference-implementations/`

Not yet complete:
- no full `operations-level-1` profile/template set
- no production-ready tool adapter implementations
- no domain-lib specs equivalent to the education pack
- no validated end-to-end test scenarios

Current structure:

```
agriculture/
├── README.md
├── runtime-config.yaml
├── operations-level-1/
│   ├── domain-physics.json
│   └── example-subject.yaml
├── prompts/
│   ├── domain-system-override.md
│   └── evidence-extraction.md
└── reference-implementations/
    └── runtime-adapters.py
```

Use this pack as an experimental reference, not as a fully validated production domain.

For authoring guidance, see [`../README.md`](../README.md) and [`../../specs/domain-profile-spec-v1.md`](../../specs/domain-profile-spec-v1.md).
