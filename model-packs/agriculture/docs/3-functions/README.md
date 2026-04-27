# runtime-adapters(3)

## NAME

`runtime_adapters.py` — Runtime adapter for the agriculture domain

## SYNOPSIS

```python
from runtime_adapters import interpret_turn_input
evidence = interpret_turn_input(turn_input, task_context, session_state)
```

## DESCRIPTION

`runtime_adapters.py` is the agriculture domain's Phase A + B synthesis controller. It
receives raw operator input, runs it through the domain's NLP pre-interpreter (if present),
assembles the evidence dict for the orchestrator, and emits the engine contract fields
(`problem_solved`, `problem_status`).

The agriculture domain currently has a single module (`operations-level-1`) covering
field-level operational decision support — signal monitoring, variance reporting, and
action-card generation for soil health, pest pressure, and moisture anomalies.

## SEE ALSO

[`domain-adapter-pattern(7)`](../../../../docs/7-concepts/domain-adapter-pattern.md),
[`domain-pack-anatomy(7)`](../../../../docs/7-concepts/domain-pack-anatomy.md)
