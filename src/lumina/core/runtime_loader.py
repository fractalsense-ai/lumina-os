# See also:
#   docs/7-concepts/domain-pack-anatomy.md
#   docs/7-concepts/domain-adapter-pattern.md
#   docs/7-concepts/execution-route-compilation.md
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from lumina.core.yaml_loader import load_yaml

log = logging.getLogger("lumina.runtime-loader")





def _load_callable(repo_root: Path, module_path: str, callable_name: str) -> Callable[..., Any]:
    abs_module_path = repo_root / module_path
    module_key = f"runtime_module_{abs_module_path.stem}_{abs_module_path.stat().st_mtime_ns}"

    # Re-use an already-executed module to avoid repeated module-level side
    # effects (e.g. multiple re.compile() calls, pydantic model re-registration)
    # when several callables are loaded from the same file.
    if module_key in sys.modules:
        cached_fn = getattr(sys.modules[module_key], callable_name, None)
        if cached_fn is not None and callable(cached_fn):
            return cached_fn

    spec = importlib.util.spec_from_file_location(module_key, str(abs_module_path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod = sys.modules[module_key]  # re-fetch; shim may have replaced entry

    fn = getattr(mod, callable_name, None)
    if fn is None or not callable(fn):
        raise RuntimeError(f"Callable '{callable_name}' not found in module {module_path}")
    return fn


def _read_text(repo_root: Path, rel_path: str) -> str:
    path = repo_root / rel_path
    if not path.exists():
        raise RuntimeError(f"Configured file not found: {rel_path}")
    return path.read_text(encoding="utf-8")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json_hash(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


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
        "turn_interpretation_prompt_path",
        "domain_physics_path",
        "subject_profile_path",
        "default_task_spec",
    ]
    for key in required_runtime_keys:
        _require_key(runtime_cfg, key, "runtime")

    # Validate referenced files exist.
    global_prompt_path = runtime_cfg.get("global_system_prompt_path", "docs/5-standards/global-system-prompt.md")
    _require_file(repo_root, _require_str(global_prompt_path, "runtime.global_system_prompt_path"), "runtime.global_system_prompt_path")
    _require_file(repo_root, _require_str(runtime_cfg["domain_system_prompt_path"], "runtime.domain_system_prompt_path"), "runtime.domain_system_prompt_path")
    _require_file(repo_root, _require_str(runtime_cfg["turn_interpretation_prompt_path"], "runtime.turn_interpretation_prompt_path"), "runtime.turn_interpretation_prompt_path")
    _require_file(repo_root, _require_str(runtime_cfg["domain_physics_path"], "runtime.domain_physics_path"), "runtime.domain_physics_path")
    _require_file(repo_root, _require_str(runtime_cfg["subject_profile_path"], "runtime.subject_profile_path"), "runtime.subject_profile_path")

    if not isinstance(runtime_cfg["default_task_spec"], dict):
        raise RuntimeError("'runtime.default_task_spec' must be a mapping/dict")

    deterministic_templates = runtime_cfg.get("deterministic_templates", {})
    if deterministic_templates is not None and not isinstance(deterministic_templates, dict):
        raise RuntimeError("'runtime.deterministic_templates' must be a mapping/dict")

    turn_input_schema = runtime_cfg.get("turn_input_schema", {})
    if turn_input_schema is not None and not isinstance(turn_input_schema, dict):
        raise RuntimeError("'runtime.turn_input_schema' must be a mapping/dict when provided")

    action_prompt_type_map = runtime_cfg.get("action_prompt_type_map", {})
    if action_prompt_type_map is not None and not isinstance(action_prompt_type_map, dict):
        raise RuntimeError("'runtime.action_prompt_type_map' must be a mapping/dict when provided")
    for action, prompt_type in (action_prompt_type_map or {}).items():
        _require_str(action, "runtime.action_prompt_type_map.<action>")
        _require_str(prompt_type, f"runtime.action_prompt_type_map.{action}")

    _validate_adapter_cfg(adapters_cfg, "state_builder")
    _validate_adapter_cfg(adapters_cfg, "domain_step")
    _validate_adapter_cfg(adapters_cfg, "turn_interpreter")

    tools_cfg = adapters_cfg.get("tools", {})
    if tools_cfg is not None and not isinstance(tools_cfg, dict):
        raise RuntimeError("'adapters.tools' must be a mapping/dict when provided")

    for tool_id, tool_cfg_raw in (tools_cfg or {}).items():
        tool_cfg = _require_dict(tool_cfg_raw, f"adapters.tools.{tool_id}")
        _require_str(_require_key(tool_cfg, "module_path", f"adapters.tools.{tool_id}"), f"adapters.tools.{tool_id}.module_path")
        _require_str(_require_key(tool_cfg, "callable", f"adapters.tools.{tool_id}"), f"adapters.tools.{tool_id}.callable")

    return runtime_cfg, adapters_cfg


def load_runtime_context(repo_root: Path, runtime_config_path: str | None = None) -> dict[str, Any]:
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

    global_prompt_path = repo_root / runtime_cfg.get("global_system_prompt_path", "docs/5-standards/global-system-prompt.md")
    domain_prompt_path = repo_root / runtime_cfg["domain_system_prompt_path"]
    turn_prompt_path = repo_root / runtime_cfg["turn_interpretation_prompt_path"]
    domain_physics_path = repo_root / runtime_cfg["domain_physics_path"]

    global_prompt = global_prompt_path.read_text(encoding="utf-8")
    domain_prompt = domain_prompt_path.read_text(encoding="utf-8")
    turn_interpretation_prompt = turn_prompt_path.read_text(encoding="utf-8")

    from lumina.core.persona_builder import build_system_prompt, PersonaContext
    system_prompt = build_system_prompt(PersonaContext.CONVERSATIONAL, domain_override=domain_prompt.strip())
    domain_physics = json.loads(domain_physics_path.read_text(encoding="utf-8"))
    if not isinstance(domain_physics, dict):
        raise RuntimeError("Configured domain physics JSON must parse to an object")

    runtime_provenance = {
        "domain_physics_hash": _canonical_json_hash(domain_physics_path),
        "global_prompt_hash": _sha256_text(global_prompt),
        "domain_prompt_hash": _sha256_text(domain_prompt),
        "turn_interpretation_prompt_hash": _sha256_text(turn_interpretation_prompt),
        "system_prompt_hash": _sha256_text(system_prompt),
        "domain_pack_id": str(domain_physics.get("id", "")),
        "domain_pack_version": str(domain_physics.get("version", "")),
    }

    state_builder_cfg = adapters_cfg["state_builder"]
    domain_step_cfg = adapters_cfg["domain_step"]
    turn_interpreter_cfg = adapters_cfg["turn_interpreter"]

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
    turn_interpreter_fn = _load_callable(
        repo_root,
        turn_interpreter_cfg["module_path"],
        turn_interpreter_cfg["callable"],
    )

    # Optional NLP pre-interpreter adapter (backward compatible).
    nlp_pre_interpreter_fn: Callable[..., Any] | None = None
    nlp_cfg = adapters_cfg.get("nlp_pre_interpreter")
    if nlp_cfg is not None:
        nlp_pre_interpreter_fn = _load_callable(
            repo_root,
            nlp_cfg["module_path"],
            nlp_cfg["callable"],
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
    deterministic_templates_mud = runtime_cfg.get("deterministic_templates_mud") or {}
    tool_call_policies = runtime_cfg.get("tool_call_policies") or {}
    if tool_call_policies is not None and not isinstance(tool_call_policies, dict):
        raise RuntimeError("'runtime.tool_call_policies' must be a mapping/dict when provided")

    ui_manifest = cfg.get("ui_manifest")
    if ui_manifest is None:
        ui_manifest = runtime_cfg.get("ui_manifest")
    if ui_manifest is not None and not isinstance(ui_manifest, dict):
        raise RuntimeError("'ui_manifest' must be a mapping/dict when provided")

    slm_weight_overrides = runtime_cfg.get("slm_weight_overrides") or {}
    if slm_weight_overrides and not isinstance(slm_weight_overrides, dict):
        raise RuntimeError("'runtime.slm_weight_overrides' must be a mapping/dict when provided")

    # Load world_sim config and eagerly resolve mud-world template list so that
    # generate_mud_world() receives a pre-populated cfg["templates"] list at
    # session initialisation time (avoids a file-read per state-builder call).
    _world_sim_cfg: dict[str, Any] | None = runtime_cfg.get("world_sim") or None
    if _world_sim_cfg is not None:
        import copy as _copy
        _world_sim_cfg = _copy.deepcopy(_world_sim_cfg)
        _mud_builder = _world_sim_cfg.get("mud_world_builder") or {}
        _tpl_rel = _mud_builder.get("templates_path", "")
        if _tpl_rel and not _mud_builder.get("templates"):
            _tpl_path = repo_root / _tpl_rel
            if _tpl_path.exists():
                _tpl_data = load_yaml(_tpl_path)
                _mud_builder["templates"] = _tpl_data.get("templates") or []
                _world_sim_cfg["mud_world_builder"] = _mud_builder

    ctx = {
        "domain_physics_path": str(domain_physics_path),
        "module_id": domain_physics.get("id", ""),
        "subject_profile_path": str(repo_root / runtime_cfg["subject_profile_path"]),
        "default_task_spec": runtime_cfg.get("default_task_spec") or {},
        "domain_step_params": runtime_cfg.get("domain_step_params") or {},
        "turn_input_defaults": runtime_cfg.get("turn_input_defaults") or {},
        "turn_input_schema": runtime_cfg.get("turn_input_schema") or {},
        "action_prompt_type_map": runtime_cfg.get("action_prompt_type_map") or {},
        "deterministic_templates": deterministic_templates,
        "deterministic_templates_mud": deterministic_templates_mud,
        "tool_call_policies": tool_call_policies,
        "slm_weight_overrides": slm_weight_overrides,
        "ui_manifest": ui_manifest,
        "system_prompt": system_prompt,
        "turn_interpretation_prompt": turn_interpretation_prompt,
        "runtime_provenance": runtime_provenance,
        "domain": domain_physics,
        "state_builder_fn": state_builder_fn,
        "domain_step_fn": domain_step_fn,
        "turn_interpreter_fn": turn_interpreter_fn,
        "nlp_pre_interpreter_fn": nlp_pre_interpreter_fn,
        "tool_fns": tool_fns,
        "world_sim": _world_sim_cfg,
        "local_only": bool(runtime_cfg.get("local_only", False)),
        "pre_turn_checks": runtime_cfg.get("pre_turn_checks") or [],
    }

    # ── Externalized domain config paths (optional) ──────────────
    # These are read by slm.py and persona_builder.py at first call time.
    # Storing them in ctx makes them discoverable by session diagnostics.
    cmd_translator_path = runtime_cfg.get("command_translator_prompt_path")
    if cmd_translator_path:
        full_ct = repo_root / cmd_translator_path
        if full_ct.is_file():
            ctx["command_translator_prompt_path"] = str(full_ct)

    admin_ops_path = runtime_cfg.get("admin_operations_schema_path")
    if admin_ops_path:
        full_ao = repo_root / admin_ops_path
        if full_ao.is_file():
            ctx["admin_operations_schema_path"] = str(full_ao)

    # ── Hierarchical profile templates (optional, Base → Domain → Role) ──
    _base_profile = runtime_cfg.get("base_profile_path")
    if _base_profile:
        _bp = repo_root / _base_profile
        if _bp.is_file():
            ctx["base_profile_path"] = str(_bp)
    _domain_ext = runtime_cfg.get("domain_profile_extension_path")
    if _domain_ext:
        _de = repo_root / _domain_ext
        if _de.is_file():
            ctx["domain_profile_extension_path"] = str(_de)
    _profile_templates = runtime_cfg.get("profile_templates")
    if isinstance(_profile_templates, dict) and _profile_templates:
        resolved_templates: dict[str, str] = {}
        for _role_key, _tpl_rel in _profile_templates.items():
            _tpl_abs = repo_root / _tpl_rel
            if _tpl_abs.is_file():
                resolved_templates[str(_role_key)] = str(_tpl_abs)
        if resolved_templates:
            ctx["profile_templates"] = resolved_templates

    # Module routing map (optional) — used by session.py for profile→physics
    _module_map = runtime_cfg.get("module_map")
    if isinstance(_module_map, dict) and _module_map:
        # Pre-compile per-module adapter overrides so session.py can swap
        # state_builder_fn / domain_step_fn for governance modules.
        for _mod_id, _mod_cfg in _module_map.items():
            _mod_adapters = _mod_cfg.get("adapters")
            if isinstance(_mod_adapters, dict):
                for _ak in ("state_builder", "domain_step", "turn_interpreter"):
                    _acfg = _mod_adapters.get(_ak)
                    if isinstance(_acfg, dict) and _acfg.get("module_path") and _acfg.get("callable"):
                        try:
                            _mod_cfg[f"{_ak}_fn"] = _load_callable(
                                repo_root, _acfg["module_path"], _acfg["callable"],
                            )
                        except Exception as _e:
                            log.warning("Failed to load module adapter %s.%s: %s", _mod_id, _ak, _e)
            # Pre-compile per-module system prompt and turn interpretation prompt
            # so governance modules get a governance-specific persona instead of
            # inheriting the domain-wide (learning) persona.
            _mod_sys_prompt_path = _mod_cfg.get("domain_system_prompt_path")
            if _mod_sys_prompt_path:
                try:
                    _mod_persona_text = _read_text(repo_root, _mod_sys_prompt_path)
                    from lumina.core.persona_builder import build_system_prompt as _bsp, PersonaContext as _PC
                    _mod_cfg["system_prompt"] = _bsp(_PC.CONVERSATIONAL, domain_override=_mod_persona_text.strip())
                except Exception as _e:
                    log.warning("Failed to load module system prompt %s: %s", _mod_id, _e)
            _mod_ti_path = _mod_cfg.get("turn_interpretation_prompt_path")
            if _mod_ti_path:
                try:
                    _mod_cfg["turn_interpretation_prompt"] = _read_text(repo_root, _mod_ti_path)
                except Exception as _e:
                    log.warning("Failed to load module turn-interp prompt %s: %s", _mod_id, _e)
            # Per-module turn_input_defaults / turn_input_schema override
            # so governance modules get governance-shaped evidence instead
            # of inheriting the domain-wide (learning) defaults.
            # See: docs/7-concepts/llm-assisted-governance-adapters.md
            _mod_tid = _mod_cfg.get("turn_input_defaults")
            if isinstance(_mod_tid, dict) and _mod_tid:
                _mod_cfg["turn_input_defaults"] = dict(_mod_tid)
            _mod_tis = _mod_cfg.get("turn_input_schema")
            if isinstance(_mod_tis, dict) and _mod_tis:
                _mod_cfg["turn_input_schema"] = dict(_mod_tis)
        ctx["module_map"] = _module_map

    # Role-to-default-module routing (optional)
    _role_to_mod = runtime_cfg.get("role_to_default_module")
    if isinstance(_role_to_mod, dict) and _role_to_mod:
        ctx["role_to_default_module"] = _role_to_mod

    # --- Optional: merge auto-discovered tool adapter metadata --------
    # Explicit runtime-config declarations always take precedence.
    try:
        from lumina.core.adapter_indexer import scan_tool_adapters, scan_group_resources

        domain_pack_dir = (repo_root / cfg_path).parent.parent
        discovered = scan_tool_adapters(domain_pack_dir)
        ctx["discovered_tool_adapters"] = {
            aid: entry.to_dict() for aid, entry in discovered.items()
        }

        # --- Group libraries and group tools from physics files --------
        libs, grp_tools = scan_group_resources(domain_pack_dir)
        ctx["group_libraries"] = {k: e.to_dict() for k, e in libs.items()}
        ctx["group_tools"] = {k: e.to_dict() for k, e in grp_tools.items()}
    except Exception:
        ctx["discovered_tool_adapters"] = {}
        ctx["group_libraries"] = {}
        ctx["group_tools"] = {}

    # --- Pre-compile execution routes ("shader cache") ----------------
    # Resolves invariant → standing-order → tool → library references into
    # flat lookup tables so the orchestrator does O(1) lookups per turn.
    try:
        from lumina.core.route_compiler import compile_execution_routes

        # Build validation indexes from available tools and libraries.
        _tool_idx = dict(tool_fns)
        _tool_idx.update(ctx.get("discovered_tool_adapters") or {})
        _lib_idx = dict(ctx.get("group_libraries") or {})

        ctx["compiled_routes"] = compile_execution_routes(
            domain_physics,
            tool_index=_tool_idx or None,
            library_index=_lib_idx or None,
            strict=False,  # warn on missing refs, don't block startup
        )
    except Exception as _rc_exc:
        log.warning("Route compilation skipped: %s", _rc_exc)
        ctx["compiled_routes"] = None

    return ctx
