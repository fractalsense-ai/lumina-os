# Changelog — Assistant Domain Pack

All notable changes to this domain pack will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-04-20

### Added
- Initial scaffold — all required and recommended files.
- `pack.yaml` with HMVC layer declarations.
- `cfg/runtime-config.yaml` with module map and intent-based routing.
- `modules/conversation/` — commons module aggregating all user-module tools.
- `modules/weather/` — weather lookup task module.
- `modules/calendar/` — calendar management task module.
- `modules/search/` — web search task module.
- `modules/creative-writing/` — creative writing task module (no tools).
- `modules/planning/` — planning and task management module.
- `modules/domain-authority/` — governance module.
- `controllers/runtime_adapters.py` with 3 required callables.
- `controllers/nlp_pre_interpreter.py` for intent classification.
- `controllers/tool_adapters.py` with stub tool implementations.
- `controllers/assistant_operations.py` ops dispatcher.
- `controllers/assistant_escalation_context.py` escalation hook.
- `domain-lib/task_tracker.py` task lifecycle state machine.
- `domain-lib/reference/turn-interpretation-spec-v1.md` turn interpretation schema.
- `domain-lib/reference/` per-module task specs.
- `profiles/entity.yaml` default entity profile.
- `cfg/domain-profile-extension.yaml` domain-wide profile layer.
- `prompts/domain-persona-v1.md` assistant persona prompt.
