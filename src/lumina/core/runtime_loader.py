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

import types

log = logging.getLogger("lumina.runtime-loader")


def _ensure_package_chain(dotted_name: str, directory: Path) -> None:
    """Register synthetic package modules so relative imports can resolve."""
    parts = dotted_name.split(".")
    for i in range(1, len(parts) + 1):
        pkg_key = ".".join(parts[:i])
        if pkg_key not in sys.modules:
            pkg_mod = types.ModuleType(pkg_key)
            pkg_mod.__package__ = pkg_key
            pkg_mod.__path__ = [str(directory)]
            sys.modules[pkg_key] = pkg_mod




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

    # Derive a dotted package name from the relative directory path so that
    # relative imports (``from .ops.foo import bar``) resolve correctly.
    rel_dir = abs_module_path.parent.relative_to(repo_root)
    package_key = "runtime_pkg_" + ".".join(rel_dir.parts)
    _ensure_package_chain(package_key, abs_module_path.parent)

    qualified_name = package_key + "." + abs_module_path.stem
    spec = importlib.util.spec_from_file_location(
        qualified_name, str(abs_module_path),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    mod.__package__ = package_key
    # Register under both keys: the cache key and the qualified name.
    # Some modules (shims) replace sys.modules[__name__] during exec — the
    # qualified name is what __name__ resolves to, so we need it present.
    sys.modules[module_key] = mod
    sys.modules[qualified_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    # Re-fetch: a shim module may have replaced the entry under either key.
    mod = sys.modules.get(qualified_name, sys.modules.get(module_key, mod))

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
            "(e.g. 'model-packs/education/runtime-config.yaml')."
        )
    cfg_path = runtime_config_path
    cfg = load_yaml(str(repo_root / cfg_path))
    if not isinstance(cfg, dict):
        raise RuntimeError(f"Runtime config must parse as a mapping/dict: {cfg_path}")

    # ── Auto-discover ui-config.yaml alongside runtime-config.yaml ──
    # Convention: if a ui-config.yaml exists in the same directory, merge
    # its top-level keys into cfg.  Inline definitions in runtime-config.yaml
    # always take precedence (only missing keys are filled in).
    _ui_cfg_path = (repo_root / cfg_path).parent / "ui-config.yaml"
    if _ui_cfg_path.is_file():
        _ui_cfg = load_yaml(str(_ui_cfg_path))
        if isinstance(_ui_cfg, dict):
            for _k, _v in _ui_cfg.items():
                if _k not in cfg:
                    cfg[_k] = _v

    runtime_cfg, adapters_cfg = _validate_runtime_config(repo_root, cfg, cfg_path)

    global_prompt_path = repo_root / runtime_cfg.get("global_system_prompt_path", "docs/5-standards/global-system-prompt.md")
    domain_prompt_path = repo_root / runtime_cfg["domain_system_prompt_path"]
    turn_prompt_path = repo_root / runtime_cfg["turn_interpretation_prompt_path"]
    domain_physics_path = repo_root / runtime_cfg["domain_physics_path"]

    global_prompt = global_prompt_path.read_text(encoding="utf-8")
    domain_prompt = domain_prompt_path.read_text(encoding="utf-8")
    turn_interpretation_prompt = turn_prompt_path.read_text(encoding="utf-8")

    # Optional multi-task turn interpretation prompt (domain opt-in).
    multi_task_interpretation_prompt: str | None = None
    _mti_prompt_path = runtime_cfg.get("multi_task_interpretation_prompt_path")
    if _mti_prompt_path:
        try:
            multi_task_interpretation_prompt = _read_text(repo_root, _mti_prompt_path)
        except Exception as _e:
            log.warning("Failed to load multi_task_interpretation_prompt: %s", _e)

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
        "model_pack_id": str(domain_physics.get("id", "")),
        "model_pack_version": str(domain_physics.get("version", "")),
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

    # Optional multi-task turn interpreter adapter (domain opt-in).
    # When registered, the framework uses this callable instead of the
    # standard turn_interpreter_fn when multi-intent signals are detected.
    multi_task_turn_interpreter_fn: Callable[..., Any] | None = None
    _mti_cfg = adapters_cfg.get("multi_task_turn_interpreter")
    if _mti_cfg is not None:
        multi_task_turn_interpreter_fn = _load_callable(
            repo_root,
            _mti_cfg["module_path"],
            _mti_cfg["callable"],
        )

    # Optional pre-turn resume hook (called when current_task is already
    # solved at session resume — lets the domain generate a replacement).
    pre_turn_resume_fn: Callable[..., Any] | None = None
    _ptr_cfg = adapters_cfg.get("pre_turn_resume")
    if _ptr_cfg is not None:
        pre_turn_resume_fn = _load_callable(
            repo_root, _ptr_cfg["module_path"], _ptr_cfg["callable"],
        )

    # Optional post-turn processor adapter (education domain uses this for
    # fluency-gated advancement, problem_solved override, etc.)
    post_turn_processor_fn: Callable[..., Any] | None = None
    _ptp_cfg = adapters_cfg.get("post_turn_processor")
    if _ptp_cfg is not None:
        post_turn_processor_fn = _load_callable(
            repo_root, _ptp_cfg["module_path"], _ptp_cfg["callable"],
        )

    # Optional post-turn timer hook (resets domain-specific timestamps).
    post_turn_timer_fn: Callable[..., Any] | None = None
    _ptt_cfg = adapters_cfg.get("post_turn_timer")
    if _ptt_cfg is not None:
        post_turn_timer_fn = _load_callable(
            repo_root, _ptt_cfg["module_path"], _ptt_cfg["callable"],
        )

    # Optional profile serializer (education domain extracts fluency/learning_state).
    profile_serializer_fn: Callable[..., Any] | None = None
    _ps_cfg = adapters_cfg.get("profile_serializer")
    if _ps_cfg is not None:
        profile_serializer_fn = _load_callable(
            repo_root, _ps_cfg["module_path"], _ps_cfg["callable"],
        )

    # Optional turn-0 presenter check (education domain presents equations).
    turn_0_presenter_fn: Callable[..., Any] | None = None
    _t0_cfg = adapters_cfg.get("turn_0_presenter")
    if _t0_cfg is not None:
        turn_0_presenter_fn = _load_callable(
            repo_root, _t0_cfg["module_path"], _t0_cfg["callable"],
        )

    # Optional escalation-context hook (supplies actor identity for cards).
    escalation_context_fn: Callable[..., Any] | None = None
    _ec_cfg = adapters_cfg.get("escalation_context")
    if _ec_cfg is not None:
        escalation_context_fn = _load_callable(
            repo_root, _ec_cfg["module_path"], _ec_cfg["callable"],
        )

    # Optional SLM normalizer hook (domain-specific role alias mapping).
    slm_normalizer_fn: Callable[..., Any] | None = None
    _sn_cfg = adapters_cfg.get("slm_normalizer")
    if _sn_cfg is not None:
        slm_normalizer_fn = _load_callable(
            repo_root, _sn_cfg["module_path"], _sn_cfg["callable"],
        )

    # Optional task initializer (creates current_task at session start).
    task_initializer_fn: Callable[..., Any] | None = None
    _ti_cfg = adapters_cfg.get("task_initializer")
    if _ti_cfg is not None:
        task_initializer_fn = _load_callable(
            repo_root, _ti_cfg["module_path"], _ti_cfg["callable"],
        )

    tool_fns: dict[str, Callable[..., Any]] = {}
    tools_cfg = adapters_cfg.get("tools") or {}
    for tool_id, tool_cfg in tools_cfg.items():
        tool_fns[str(tool_id)] = _load_callable(
            repo_root,
            tool_cfg["module_path"],
            tool_cfg["callable"],
        )

    # ── Optional domain-owned API routes ─────────────────────────
    # Each entry declares {path, method, module_path, callable, roles, ...}.
    # The loaded callable is stored alongside the route metadata so the
    # server can mount it dynamically at startup.
    api_route_defs: list[dict[str, Any]] = []
    api_routes_cfg = adapters_cfg.get("api_routes") or {}
    for route_id, route_cfg in api_routes_cfg.items():
        if not isinstance(route_cfg, dict):
            continue
        _rmod = route_cfg.get("module_path")
        _rcall = route_cfg.get("callable")
        if not _rmod or not _rcall:
            log.warning("api_routes.%s: missing module_path or callable — skipped", route_id)
            continue
        try:
            _rfn = _load_callable(repo_root, _rmod, _rcall)
        except Exception as _e:
            log.warning("api_routes.%s: failed to load callable — %s", route_id, _e)
            continue
        api_route_defs.append({
            "id": str(route_id),
            "path": route_cfg.get("path", ""),
            "method": (route_cfg.get("method") or "GET").upper(),
            "handler_fn": _rfn,
            "roles": route_cfg.get("roles") or [],
            "request_body": route_cfg.get("request_body") or {},
            "commit_guard": bool(route_cfg.get("commit_guard", False)),
        })

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

    # ── Domain-pack UI plugin metadata (plugin_bundle, slash_commands, dashboard_tabs) ──
    ui_plugin = cfg.get("ui")
    if ui_plugin is not None and not isinstance(ui_plugin, dict):
        raise RuntimeError("'ui' must be a mapping/dict when provided")

    slm_weight_overrides = runtime_cfg.get("slm_weight_overrides") or {}
    if slm_weight_overrides and not isinstance(slm_weight_overrides, dict):
        raise RuntimeError("'runtime.slm_weight_overrides' must be a mapping/dict when provided")

    _world_sim_cfg = runtime_cfg.get("world_sim") or None

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
        "ui_plugin": ui_plugin,
        "system_prompt": system_prompt,
        "turn_interpretation_prompt": turn_interpretation_prompt,
        "multi_task_interpretation_prompt": multi_task_interpretation_prompt,
        "runtime_provenance": runtime_provenance,
        "domain": domain_physics,
        "state_builder_fn": state_builder_fn,
        "domain_step_fn": domain_step_fn,
        "turn_interpreter_fn": turn_interpreter_fn,
        "nlp_pre_interpreter_fn": nlp_pre_interpreter_fn,
        "multi_task_turn_interpreter_fn": multi_task_turn_interpreter_fn,
        "pre_turn_resume_fn": pre_turn_resume_fn,
        "post_turn_processor_fn": post_turn_processor_fn,
        "post_turn_timer_fn": post_turn_timer_fn,
        "profile_serializer_fn": profile_serializer_fn,
        "turn_0_presenter_fn": turn_0_presenter_fn,
        "escalation_context_fn": escalation_context_fn,
        "slm_normalizer_fn": slm_normalizer_fn,
        "task_initializer_fn": task_initializer_fn,
        "tool_fns": tool_fns,
        "api_route_defs": api_route_defs,
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
        # ── Auto-discover module-config.yaml sidecars ──────────────────
        # Convention: if an entry has `module_path`, look for a
        # module-config.yaml in that directory and merge its keys.
        # Inline keys in runtime-config.yaml always win (same semantics
        # as ui-config.yaml auto-discovery).
        for _mod_id, _mod_cfg in _module_map.items():
            _mod_dir = _mod_cfg.get("module_path")
            if _mod_dir:
                _mc_path = repo_root / _mod_dir / "module-config.yaml"
                if _mc_path.is_file():
                    _mc = load_yaml(str(_mc_path))
                    if isinstance(_mc, dict):
                        for _k, _v in _mc.items():
                            if _k not in _mod_cfg:
                                _mod_cfg[_k] = _v
            # Pre-load module domain physics so the enrichment pipeline can
            # access module-specific glossaries without a runtime disk read.
            _mod_dp = _mod_cfg.get("domain_physics_path")
            if _mod_dp:
                _mod_dp_file = repo_root / _mod_dp
                if _mod_dp_file.is_file():
                    # Resolve to absolute path so session.py can open it
                    # regardless of the server's working directory.
                    _mod_cfg["domain_physics_path"] = str(_mod_dp_file)
                    try:
                        _mod_cfg["domain_physics"] = json.loads(
                            _mod_dp_file.read_text(encoding="utf-8")
                        )
                    except Exception as _e:
                        log.warning(
                            "Failed to pre-load module physics for %s: %s", _mod_id, _e
                        )

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
                # Per-module NLP pre-interpreter override
                _mod_nlp_cfg = _mod_adapters.get("nlp_pre_interpreter")
                if isinstance(_mod_nlp_cfg, dict) and _mod_nlp_cfg.get("module_path") and _mod_nlp_cfg.get("callable"):
                    try:
                        _mod_cfg["nlp_pre_interpreter_fn"] = _load_callable(
                            repo_root, _mod_nlp_cfg["module_path"], _mod_nlp_cfg["callable"],
                        )
                    except Exception as _e:
                        log.warning("Failed to load module NLP adapter %s: %s", _mod_id, _e)
                # Per-module optional hook overrides (post_turn_processor, etc.)
                for _hk in ("post_turn_processor", "post_turn_timer", "profile_serializer", "turn_0_presenter", "escalation_context", "task_initializer"):
                    _hcfg = _mod_adapters.get(_hk)
                    if isinstance(_hcfg, dict) and _hcfg.get("module_path") and _hcfg.get("callable"):
                        try:
                            _mod_cfg[f"{_hk}_fn"] = _load_callable(
                                repo_root, _hcfg["module_path"], _hcfg["callable"],
                            )
                        except Exception as _e:
                            log.warning("Failed to load module hook %s.%s: %s", _mod_id, _hk, _e)
                # Per-module tool overrides (merged with domain-wide tools)
                _mod_tools_cfg = _mod_adapters.get("tools")
                if isinstance(_mod_tools_cfg, dict) and _mod_tools_cfg:
                    _mod_tool_fns: dict[str, Callable[..., Any]] = {}
                    for _tid, _tcfg in _mod_tools_cfg.items():
                        if isinstance(_tcfg, dict) and _tcfg.get("module_path") and _tcfg.get("callable"):
                            try:
                                _mod_tool_fns[str(_tid)] = _load_callable(
                                    repo_root, _tcfg["module_path"], _tcfg["callable"],
                                )
                            except Exception as _e:
                                log.warning("Failed to load module tool %s.%s: %s", _mod_id, _tid, _e)
                    if _mod_tool_fns:
                        _mod_cfg["tool_fns"] = _mod_tool_fns
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
            _mod_mti_path = _mod_cfg.get("multi_task_interpretation_prompt_path")
            if _mod_mti_path:
                try:
                    _mod_cfg["multi_task_interpretation_prompt"] = _read_text(repo_root, _mod_mti_path)
                except Exception as _e:
                    log.warning("Failed to load module multi-task-interp prompt %s: %s", _mod_id, _e)
            # Per-module turn_input_defaults / turn_input_schema override
            # so governance modules get governance-shaped evidence instead
            # of inheriting the domain-wide (learning) defaults.
            # See: docs/8-admin/llm-assisted-governance-adapters.md
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
