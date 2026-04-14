"""Domain-level problem generator router.

Dispatches to the per-module generator based on ``domain_id``.
Each curriculum module keeps its own ``problem_generator.py`` with
tier keys matching its ``equation_difficulty_tiers``.

This router is the single entry point used by the commons module
(general-education) and any adapter that needs cross-module access.

Usage::

    from domain-packs.education.controllers.problem_generator import generate_problem
    problem = generate_problem(difficulty, subsystem_configs, domain_id="domain/edu/algebra-1/v1")
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_MODULE_DIR = Path(__file__).resolve().parent.parent / "modules"

_GENERATOR_PATHS: dict[str, Path] = {
    "domain/edu/pre-algebra/v1": _MODULE_DIR / "pre-algebra" / "problem_generator.py",
    "domain/edu/algebra-intro/v1": _MODULE_DIR / "algebra-intro" / "problem_generator.py",
    "domain/edu/algebra-1/v1": _MODULE_DIR / "algebra-1" / "problem_generator.py",
    "domain/edu/algebra-level-1/v1": _MODULE_DIR / "algebra-level-1" / "problem_generator.py",
}

_loaded_modules: dict[str, Any] = {}


def _load_generator(domain_id: str) -> Any:
    """Lazy-load and cache the per-module generator."""
    if domain_id in _loaded_modules:
        return _loaded_modules[domain_id]

    gen_path = _GENERATOR_PATHS.get(domain_id)
    if gen_path is None or not gen_path.exists():
        raise ValueError(
            f"No problem generator registered for domain_id={domain_id!r}"
        )

    module_name = f"_gen_{domain_id.replace('/', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, str(gen_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    _loaded_modules[domain_id] = mod
    return mod


def select_tier(
    difficulty: float,
    tiers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the tier whose ``[min_difficulty, max_difficulty)`` range
    contains *difficulty*.  Falls back to the last tier.

    Re-exported here for backwards compatibility with code that imports
    from the controller rather than a per-module generator.
    """
    for tier in tiers:
        lo = float(tier.get("min_difficulty", 0.0))
        hi = float(tier.get("max_difficulty", 1.0))
        if lo <= difficulty < hi:
            return tier
    return tiers[-1]


def generate_problem(
    difficulty: float,
    subsystem_configs: dict[str, Any],
    *,
    domain_id: str | None = None,
) -> dict[str, Any]:
    """Route to the correct per-module generator.

    Parameters
    ----------
    difficulty : float
        ZPD-derived difficulty in [0, 1].
    subsystem_configs : dict
        The ``subsystem_configs`` block from domain-physics.
    domain_id : str, optional
        The module's domain id (e.g. ``"domain/edu/pre-algebra/v1"``).
        Falls back to algebra-level-1 for backwards compatibility.
    """
    if domain_id is None:
        domain_id = "domain/edu/algebra-level-1/v1"
    mod = _load_generator(domain_id)
    return mod.generate_problem(difficulty, subsystem_configs)


def initialize_task(
    task_spec: dict[str, Any],
    runtime: dict[str, Any],
    *,
    domain_id: str | None = None,
) -> dict[str, Any]:
    """Domain-level task initializer adapter.

    Extracts education-specific parameters from the generic
    ``(task_spec, runtime)`` contract and delegates to the
    per-module ``generate_problem`` via the router.
    """
    difficulty = float(task_spec.get("nominal_difficulty", 0.5))
    subsystem_configs = (runtime.get("domain") or {}).get("subsystem_configs") or {}
    return generate_problem(difficulty, subsystem_configs, domain_id=domain_id)