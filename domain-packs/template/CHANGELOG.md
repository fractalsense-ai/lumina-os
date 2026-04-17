# Changelog — Template Domain Pack

All notable changes to this domain pack will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-04-17

### Added
- Initial template scaffold — all required and recommended files.
- `pack.yaml` with HMVC layer declarations.
- `cfg/runtime-config.yaml` with every documented section and inline TODOs.
- `modules/example-module/` with domain-physics YAML+JSON, tool adapter example.
- `controllers/runtime_adapters.py` with 3 required callables.
- `controllers/nlp_pre_interpreter.py` with Phase A stub.
- `controllers/template_operations.py` ops dispatcher skeleton.
- `controllers/ops/_helpers.py` with guard/profile/commitment patterns.
- `profiles/entity.yaml` default entity profile.
- `cfg/domain-profile-extension.yaml` domain-wide profile layer.
- `prompts/domain-persona-v1.md` persona template.
- `domain-lib/reference/turn-interpretation-spec-v1.md` turn interpretation schema.
