from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable


def _load_yaml_loader(repo_root: Path) -> Callable[[str], dict[str, Any]]:
    yaml_loader_path = repo_root / "reference-implementations" / "yaml-loader.py"
    spec = importlib.util.spec_from_file_location("runtime_yaml_loader", str(yaml_loader_path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["runtime_yaml_loader"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.load_yaml


def _load_callable(repo_root: Path, module_path: str, callable_name: str) -> Callable[..., Any]:
    abs_module_path = repo_root / module_path
    module_key = f"runtime_module_{abs_module_path.stem}_{abs_module_path.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(module_key, str(abs_module_path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    fn = getattr(mod, callable_name, None)
    if fn is None or not callable(fn):
        raise RuntimeError(f"Callable '{callable_name}' not found in module {module_path}")
    return fn


def _read_text(repo_root: Path, rel_path: str) -> str:
    path = repo_root / rel_path
    if not path.exists():
        raise RuntimeError(f"Configured file not found: {rel_path}")
    return path.read_text(encoding="utf-8")


def _require_dict(value: Any, key_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"'{key_name}' must be a mapping/dict")
    return value


def _require_str(value: Any, key_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"'{key_name}' must be a non-empty string")
    return value


def _require_key(mapping: dict[str, Any], key: str, section: str) -> Any:
    if key not in mapping:
        raise RuntimeError(f"Missing required key '{section}.{key}' in runtime config")
    return mapping[key]


def _require_file(repo_root: Path, rel_path: str, key_name: str) -> Path:
    path = repo_root / rel_path
    if not path.exists():
        raise RuntimeError(f"Configured file for '{key_name}' not found: {rel_path}")
    return path


def _validate_adapter_cfg(adapters_cfg: dict[str, Any], adapter_key: str) -> dict[str, Any]:
    raw = _require_key(adapters_cfg, adapter_key, "adapters")
    cfg = _require_dict(raw, f"adapters.{adapter_key}")
    _require_str(_require_key(cfg, "module_path", f"adapters.{adapter_key}"), f"adapters.{adapter_key}.module_path")
    _require_str(_require_key(cfg, "callable", f"adapters.{adapter_key}"), f"adapters.{adapter_key}.callable")
    return cfg


def _validate_runtime_config(repo_root: Path, cfg: dict[str, Any], cfg_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime_cfg = _require_dict(_require_key(cfg, "runtime", "root"), "runtime")
    adapters_cfg = _require_dict(_require_key(cfg, "adapters", "root"), "adapters")

    required_runtime_keys = [
        "domain_system_prompt_path",
        "evidence_extraction_prompt_path",
        "domain_physics_path",
        "subject_profile_path",
        "default_task_spec",
    ]
    for key in required_runtime_keys:
        _require_key(runtime_cfg, key, "runtime")

    # Validate referenced files exist.
    global_prompt_path = runtime_cfg.get("global_system_prompt_path", "specs/global-system-prompt-v1.md")
    _require_file(repo_root, _require_str(global_prompt_path, "runtime.global_system_prompt_path"), "runtime.global_system_prompt_path")
    _require_file(repo_root, _require_str(runtime_cfg["domain_system_prompt_path"], "runtime.domain_system_prompt_path"), "runtime.domain_system_prompt_path")
    _require_file(repo_root, _require_str(runtime_cfg["evidence_extraction_prompt_path"], "runtime.evidence_extraction_prompt_path"), "runtime.evidence_extraction_prompt_path")
    _require_file(repo_root, _require_str(runtime_cfg["domain_physics_path"], "runtime.domain_physics_path"), "runtime.domain_physics_path")
    _require_file(repo_root, _require_str(runtime_cfg["subject_profile_path"], "runtime.subject_profile_path"), "runtime.subject_profile_path")

    if not isinstance(runtime_cfg["default_task_spec"], dict):
        raise RuntimeError("'runtime.default_task_spec' must be a mapping/dict")

    deterministic_templates = runtime_cfg.get("deterministic_templates", {})
    if deterministic_templates is not None and not isinstance(deterministic_templates, dict):
        raise RuntimeError("'runtime.deterministic_templates' must be a mapping/dict")

    _validate_adapter_cfg(adapters_cfg, "state_builder")
    _validate_adapter_cfg(adapters_cfg, "domain_step")
    _validate_adapter_cfg(adapters_cfg, "evidence_extractor")

    tools_cfg = adapters_cfg.get("tools", {})
    if tools_cfg is not None and not isinstance(tools_cfg, dict):
        raise RuntimeError("'adapters.tools' must be a mapping/dict when provided")

    for tool_id, tool_cfg_raw in (tools_cfg or {}).items():
        tool_cfg = _require_dict(tool_cfg_raw, f"adapters.tools.{tool_id}")
        _require_str(_require_key(tool_cfg, "module_path", f"adapters.tools.{tool_id}"), f"adapters.tools.{tool_id}.module_path")
        _require_str(_require_key(tool_cfg, "callable", f"adapters.tools.{tool_id}"), f"adapters.tools.{tool_id}.callable")

    return runtime_cfg, adapters_cfg


def load_runtime_context(repo_root: Path, runtime_config_path: str | None = None) -> dict[str, Any]:
    load_yaml = _load_yaml_loader(repo_root)

    if not runtime_config_path:
        raise RuntimeError(
            "No runtime config specified. Set LUMINA_RUNTIME_CONFIG_PATH "
            "(e.g. 'domain-packs/education/runtime-config.yaml')."
        )
    cfg_path = runtime_config_path
    cfg = load_yaml(str(repo_root / cfg_path))
    if not isinstance(cfg, dict):
        raise RuntimeError(f"Runtime config must parse as a mapping/dict: {cfg_path}")

    runtime_cfg, adapters_cfg = _validate_runtime_config(repo_root, cfg, cfg_path)

    global_prompt = _read_text(repo_root, runtime_cfg.get("global_system_prompt_path", "specs/global-system-prompt-v1.md"))
    domain_prompt = _read_text(repo_root, runtime_cfg["domain_system_prompt_path"])
    evidence_prompt = _read_text(repo_root, runtime_cfg["evidence_extraction_prompt_path"])

    state_builder_cfg = adapters_cfg["state_builder"]
    domain_step_cfg = adapters_cfg["domain_step"]
    evidence_extractor_cfg = adapters_cfg["evidence_extractor"]

    state_builder_fn = _load_callable(
        repo_root,
        state_builder_cfg["module_path"],
        state_builder_cfg["callable"],
    )
    domain_step_fn = _load_callable(
        repo_root,
        domain_step_cfg["module_path"],
        domain_step_cfg["callable"],
    )
    evidence_extractor_fn = _load_callable(
        repo_root,
        evidence_extractor_cfg["module_path"],
        evidence_extractor_cfg["callable"],
    )

    tool_fns: dict[str, Callable[..., Any]] = {}
    tools_cfg = adapters_cfg.get("tools") or {}
    for tool_id, tool_cfg in tools_cfg.items():
        tool_fns[str(tool_id)] = _load_callable(
            repo_root,
            tool_cfg["module_path"],
            tool_cfg["callable"],
        )

    deterministic_templates = runtime_cfg.get("deterministic_templates") or {}
    tool_call_policies = runtime_cfg.get("tool_call_policies") or {}
    if tool_call_policies is not None and not isinstance(tool_call_policies, dict):
        raise RuntimeError("'runtime.tool_call_policies' must be a mapping/dict when provided")

    return {
        "domain_physics_path": str(repo_root / runtime_cfg["domain_physics_path"]),
        "subject_profile_path": str(repo_root / runtime_cfg["subject_profile_path"]),
        "default_task_spec": runtime_cfg.get("default_task_spec") or {},
        "domain_step_params": runtime_cfg.get("domain_step_params") or {},
        "evidence_defaults": runtime_cfg.get("evidence_defaults") or {},
        "deterministic_templates": deterministic_templates,
        "tool_call_policies": tool_call_policies,
        "system_prompt": f"{global_prompt.strip()}\n\n# DOMAIN CONFIGURATION\n{domain_prompt.strip()}",
        "evidence_extraction_prompt": evidence_prompt,
        "state_builder_fn": state_builder_fn,
        "domain_step_fn": domain_step_fn,
        "evidence_extractor_fn": evidence_extractor_fn,
        "tool_fns": tool_fns,
    }
