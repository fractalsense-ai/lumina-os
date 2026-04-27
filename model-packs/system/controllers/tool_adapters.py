"""tool_adapters.py — System-domain tool adapters.

Each function accepts a ``payload`` dict and returns a dict result.
These are registered under ``adapters.tools`` in the system domain's
runtime-config.yaml and invoked via ``invoke_runtime_tool()`` in the
server when the command-dispatch layer resolves to a tool call.

Includes both read-only query tools and deterministic verification tools.
Verification tools are called post-SLM by the system ``interpret_turn_input``
to populate invariant-checkable evidence fields with ground truth — the same
pattern used by the education domain's algebra parser override.

No imports from ``lumina.api`` or ``lumina.core`` are allowed here —
adapters must be self-contained so they can be loaded and tested
independently of the server.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# Repo root is 4 parents up: controllers/ → system/ → model-packs/ → project-lumina/
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]

_DEFAULT_LOG_DIR = Path(tempfile.gettempdir()) / "lumina-log"
_LOG_DIR: Path = Path(os.environ.get("LUMINA_LOG_DIR", os.environ.get("LUMINA_CTL_DIR", str(_DEFAULT_LOG_DIR))))

_DOMAIN_REGISTRY_PATH: Path = _REPO_ROOT / "model-packs" / "system" / "cfg" / "domain-registry.yaml"
_ADMIN_OPS_PATH: Path = _REPO_ROOT / "model-packs" / "system" / "cfg" / "admin-operations.yaml"

# Patterns that indicate internal state leakage when found in CI output.
_INTERNAL_STATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bconfidence[_\s]*(?:score|level|rating)\s*[:=]\s*\d", re.IGNORECASE),
    re.compile(r"\bpolicy[_\s]*gate\b", re.IGNORECASE),
    re.compile(r"\binvariant[_\s]*(?:check|violation|result)\b", re.IGNORECASE),
    re.compile(r"\bstanding[_\s]*order\b.*\b(?:fire|trigger|exhaust)", re.IGNORECASE),
    re.compile(r"\bescalation[_\s]*(?:id|sla|trigger)\b", re.IGNORECASE),
    re.compile(r"\bsession[_\s]*state\b.*\bjson\b", re.IGNORECASE),
    re.compile(r"\bhash[_\s]*chain\b", re.IGNORECASE),
    re.compile(r"\bweight[_\s]*(?:override|classification)\b", re.IGNORECASE),
    re.compile(r"\bprompt[_\s]*contract\b.*\b(?:internal|raw)\b", re.IGNORECASE),
]


def _load_yaml(path: Path) -> Any:
    """Load a YAML file; returns the parsed object or raises."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("PyYAML is required for system tool adapters") from exc
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    """Load all valid JSON records from a JSONL file; skip malformed lines."""
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    records.append(rec)
            except json.JSONDecodeError:
                pass
    return records


def _scan_all_log_records(log_dir: Path) -> list[dict[str, Any]]:
    """Return all System Log records across every JSONL ledger in *log_dir*."""
    all_records: list[dict[str, Any]] = []
    if not log_dir.is_dir():
        return all_records
    for ledger_path in sorted(log_dir.glob("session-*.jsonl")):
        all_records.extend(_load_jsonl_records(ledger_path))
    return all_records


# ---------------------------------------------------------------------------
# Tool adapter functions
# ---------------------------------------------------------------------------


def list_domains(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a summary of every domain registered in domain-registry.yaml.

    Payload keys (all optional):
        include_keywords (bool): include the keyword list for each domain (default False)

    Returns:
        {
            "domains": [
                {"domain_id": str, "label": str, "module_prefix": str,
                 "description": str, "keywords": [...] (if requested)},
                ...
            ],
            "default_domain": str,
            "role_defaults": {role: domain_id, ...},
            "count": int,
        }
    """
    include_keywords: bool = bool(payload.get("include_keywords", False))

    registry = _load_yaml(_DOMAIN_REGISTRY_PATH)
    if not isinstance(registry, dict):
        return {"error": "domain-registry.yaml did not parse to a mapping", "domains": []}

    domains_cfg: dict[str, Any] = registry.get("domains") or {}
    out: list[dict[str, Any]] = []
    for domain_id, cfg in domains_cfg.items():
        if not isinstance(cfg, dict):
            continue
        entry: dict[str, Any] = {
            "domain_id": str(domain_id),
            "label": str(cfg.get("label", "")),
            "module_prefix": str(cfg.get("module_prefix", "")),
            "description": str(cfg.get("description", "")),
        }
        if include_keywords:
            entry["keywords"] = cfg.get("keywords") or []
        out.append(entry)

    return {
        "domains": out,
        "default_domain": str(registry.get("default_domain", "")),
        "role_defaults": dict(registry.get("role_defaults") or {}),
        "count": len(out),
    }


def list_modules(payload: dict[str, Any]) -> dict[str, Any]:
    """Return all modules registered for a given domain.

    Payload keys:
        domain_id (str, required): e.g. "education", "agriculture", "system"

    Returns:
        {
            "domain_id": str,
            "modules": [{"module_id": str, "domain_physics_path": str}, ...],
            "count": int,
        }
    """
    domain_id = str(payload.get("domain_id", ""))
    if not domain_id:
        return {"error": "domain_id is required", "modules": []}

    registry = _load_yaml(_DOMAIN_REGISTRY_PATH)
    if not isinstance(registry, dict):
        return {"error": "domain-registry.yaml did not parse to a mapping", "modules": []}

    domains_cfg: dict[str, Any] = registry.get("domains") or {}
    domain_cfg = domains_cfg.get(domain_id)
    if not isinstance(domain_cfg, dict):
        return {"error": f"Domain '{domain_id}' not found", "modules": []}

    runtime_cfg_path = _REPO_ROOT / domain_cfg["runtime_config_path"]
    try:
        runtime_raw = _load_yaml(runtime_cfg_path)
    except Exception:
        return {"error": f"Could not load runtime config for {domain_id}", "modules": []}

    runtime = runtime_raw.get("runtime") or runtime_raw
    modules: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Collect from module_map
    module_map = runtime.get("module_map") or {}
    for mod_id, mod_cfg in module_map.items():
        if mod_id not in seen:
            seen.add(mod_id)
            modules.append({
                "module_id": mod_id,
                "domain_physics_path": mod_cfg.get("domain_physics_path", ""),
            })

    # Default module
    default_dp = runtime.get("domain_physics_path", "")
    if default_dp:
        try:
            dp_full = _REPO_ROOT / default_dp
            with open(dp_full, encoding="utf-8") as fh:
                dp_data = json.loads(fh.read())
            default_mod_id = dp_data.get("id", "")
        except Exception:
            default_mod_id = ""
        if default_mod_id and default_mod_id not in seen:
            modules.append({
                "module_id": default_mod_id,
                "domain_physics_path": default_dp,
            })

    return {
        "domain_id": domain_id,
        "modules": modules,
        "count": len(modules),
    }


def show_domain_physics(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a summary of domain-physics for *domain_id*.

    Payload keys:
        domain_id (str, required): e.g. "education", "agriculture", "system"
        include_glossary (bool): include full glossary list (default False)
        include_topics (bool): include topics list (default True)

    Returns:
        {
            "id": str, "version": str, "label": str, "description": str,
            "domain": str, "topics": [...], "glossary": [...],
            "permissions": {...},
        }
    """
    domain_id: str = str(payload.get("domain_id") or "").strip()
    if not domain_id:
        return {"error": "payload.domain_id is required"}

    include_glossary: bool = bool(payload.get("include_glossary", False))
    include_topics: bool = bool(payload.get("include_topics", True))

    registry = _load_yaml(_DOMAIN_REGISTRY_PATH)
    if not isinstance(registry, dict):
        return {"error": "domain-registry.yaml did not parse to a mapping"}

    domain_cfg = (registry.get("domains") or {}).get(domain_id)
    if not isinstance(domain_cfg, dict):
        return {"error": f"Unknown domain_id: {domain_id!r}"}

    runtime_config_path = _REPO_ROOT / str(domain_cfg.get("runtime_config_path", ""))
    if not runtime_config_path.exists():
        return {"error": f"runtime-config.yaml not found for domain {domain_id!r}"}

    runtime_cfg = _load_yaml(runtime_config_path)
    if not isinstance(runtime_cfg, dict):
        return {"error": "runtime-config.yaml did not parse to a mapping"}

    runtime_section = runtime_cfg.get("runtime") or runtime_cfg
    physics_rel: str = str(runtime_section.get("domain_physics_path", ""))
    if not physics_rel:
        return {"error": f"No domain_physics_path in runtime config for {domain_id!r}"}

    physics_path = _REPO_ROOT / physics_rel
    if not physics_path.exists():
        return {"error": f"domain-physics file not found: {physics_rel}"}

    with open(physics_path, encoding="utf-8") as fh:
        physics: dict[str, Any] = json.load(fh)

    result: dict[str, Any] = {
        "id": physics.get("id", ""),
        "version": physics.get("version", ""),
        "label": physics.get("label", ""),
        "description": physics.get("description", ""),
        # Physics files may omit "domain"; fall back to the registry key.
        "domain": physics.get("domain") or domain_id,
        "permissions": physics.get("permissions", {}),
    }
    if include_topics:
        result["topics"] = physics.get("topics") or []
    if include_glossary:
        result["glossary"] = physics.get("glossary") or []

    return result


def module_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the operational status of a domain module.

    Resolves the domain-physics hash and checks whether a matching
    System Log commitment record exists.  This is a read-only health check —
    it does not modify any state.

    Payload keys:
        domain_id (str, required): e.g. "education", "system"

    Returns:
        {
            "domain_id": str,
            "physics_hash": str,
            "committed": bool,
            "commitment_count": int,
            "status": "ok" | "uncommitted" | "unknown",
        }
    """
    import hashlib

    domain_id: str = str(payload.get("domain_id") or "").strip()
    if not domain_id:
        return {"error": "payload.domain_id is required"}

    registry = _load_yaml(_DOMAIN_REGISTRY_PATH)
    if not isinstance(registry, dict):
        return {"error": "domain-registry.yaml did not parse to a mapping"}

    domain_cfg = (registry.get("domains") or {}).get(domain_id)
    if not isinstance(domain_cfg, dict):
        return {"error": f"Unknown domain_id: {domain_id!r}"}

    runtime_config_path = _REPO_ROOT / str(domain_cfg.get("runtime_config_path", ""))
    if not runtime_config_path.exists():
        return {"error": f"runtime-config.yaml not found for domain {domain_id!r}"}

    runtime_cfg = _load_yaml(runtime_config_path)
    if not isinstance(runtime_cfg, dict):
        return {"error": "runtime-config.yaml did not parse to a mapping"}

    runtime_section = runtime_cfg.get("runtime") or runtime_cfg
    physics_rel: str = str(runtime_section.get("domain_physics_path", ""))
    physics_path = _REPO_ROOT / physics_rel if physics_rel else None

    physics_hash: str = ""
    if physics_path and physics_path.exists():
        raw = physics_path.read_bytes()
        physics_hash = hashlib.sha256(raw).hexdigest()

    # Scan System Log for CommitmentRecords that reference this physics hash.
    all_records = _scan_all_log_records(_LOG_DIR)
    matching_commitments = [
        r for r in all_records
        if r.get("record_type") == "CommitmentRecord"
        and r.get("subject_hash") == physics_hash
    ]

    committed = len(matching_commitments) > 0
    return {
        "domain_id": domain_id,
        "physics_hash": physics_hash,
        "committed": committed,
        "commitment_count": len(matching_commitments),
        "status": "ok" if committed else ("uncommitted" if physics_hash else "unknown"),
    }


def list_escalations(payload: dict[str, Any]) -> dict[str, Any]:
    """Return recent escalation records from the System Logs.

    Payload keys (all optional):
        limit (int): max records to return (default 10, max 100)
        domain_id (str): filter by domain_id field
        status (str): filter by escalation status field (e.g. "open", "resolved")

    Returns:
        {
            "escalations": [...],
            "count": int,
            "total_scanned": int,
        }
    """
    limit: int = min(int(payload.get("limit") or 10), 100)
    filter_domain: str = str(payload.get("domain_id") or "").strip()
    filter_status: str = str(payload.get("status") or "").strip()

    all_records = _scan_all_log_records(_LOG_DIR)
    escalations = [r for r in all_records if r.get("record_type") == "EscalationRecord"]

    if filter_domain:
        escalations = [r for r in escalations if r.get("domain_id") == filter_domain]
    if filter_status:
        escalations = [r for r in escalations if r.get("status") == filter_status]

    # Most recent first (sort by timestamp descending).
    escalations.sort(key=lambda r: r.get("timestamp_utc", ""), reverse=True)
    page = escalations[:limit]

    return {
        "escalations": page,
        "count": len(page),
        "total_scanned": len(escalations),
    }


def list_log_records(payload: dict[str, Any]) -> dict[str, Any]:
    """Return recent System Log records across all sessions.

    Payload keys (all optional):
        limit (int): max records to return (default 20, max 200)
        record_type (str): filter by record_type (e.g. "TraceEvent", "CommitmentRecord")
        domain_id (str): filter by domain_id field
        session_id (str): filter by session_id field

    Returns:
        {
            "records": [...],
            "count": int,
            "total_scanned": int,
        }
    """
    limit: int = min(int(payload.get("limit") or 20), 200)
    filter_record_type: str = str(payload.get("record_type") or "").strip()
    filter_domain: str = str(payload.get("domain_id") or "").strip()
    filter_session: str = str(payload.get("session_id") or "").strip()

    all_records = _scan_all_log_records(_LOG_DIR)

    filtered = all_records
    if filter_record_type:
        filtered = [r for r in filtered if r.get("record_type") == filter_record_type]
    if filter_domain:
        filtered = [r for r in filtered if r.get("domain_id") == filter_domain]
    if filter_session:
        filtered = [r for r in filtered if r.get("session_id") == filter_session]

    # Most recent first.
    filtered.sort(key=lambda r: r.get("timestamp_utc", ""), reverse=True)
    page = filtered[:limit]

    return {
        "records": page,
        "count": len(page),
        "total_scanned": len(filtered),
    }


# ---------------------------------------------------------------------------
# Deterministic verification tools
# ---------------------------------------------------------------------------
# These tools populate invariant-checkable evidence fields with ground truth.
# Called by interpret_turn_input() after SLM extraction — same pattern as the
# education domain's algebra parser override.


def validate_command_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a SLM command-dispatch payload against admin-operations.yaml.

    Payload keys:
        command_dispatch (dict): The structured command from slm_parse_admin_command.
            Expected shape: {"operation_id": str, "params": dict}

    Returns:
        {
            "valid": bool,
            "operation_id": str,
            "missing_params": [...],
            "unknown_params": [...],
            "error": str | None,
        }
    """
    dispatch = payload.get("command_dispatch")
    if not dispatch or not isinstance(dispatch, dict):
        return {"valid": False, "operation_id": "", "missing_params": [],
                "unknown_params": [], "error": "no command_dispatch provided"}

    op_id = str(dispatch.get("operation_id") or dispatch.get("operation") or dispatch.get("name") or "")
    cmd_params = dispatch.get("params") or {}
    if not isinstance(cmd_params, dict):
        cmd_params = {}

    if not op_id:
        return {"valid": False, "operation_id": "", "missing_params": [],
                "unknown_params": [], "error": "operation_id is empty"}

    # Load admin-operations.yaml
    try:
        ops_data = _load_yaml(_ADMIN_OPS_PATH)
    except Exception:
        return {"valid": False, "operation_id": op_id, "missing_params": [],
                "unknown_params": [], "error": "could not load admin-operations.yaml"}

    ops_list = (ops_data or {}).get("operations") or []
    schema_entry = None
    for entry in ops_list:
        if isinstance(entry, dict) and entry.get("name") == op_id:
            schema_entry = entry
            break

    if schema_entry is None:
        return {"valid": False, "operation_id": op_id, "missing_params": [],
                "unknown_params": [], "error": f"unknown operation: {op_id}"}

    expected_params: dict[str, str] = schema_entry.get("params") or {}
    # Only flag params as missing if their description does not mark them
    # as optional or conditional ("omit for ...").  Schema descriptions
    # already carry this metadata in free-text form.
    required_keys = {
        k for k, v in expected_params.items()
        if "optional" not in str(v).lower() and "omit" not in str(v).lower()
    }
    provided_keys = set(cmd_params.keys())

    missing = sorted(required_keys - provided_keys)
    unknown = sorted(provided_keys - set(expected_params.keys()))

    return {
        "valid": len(missing) == 0 and len(unknown) == 0,
        "operation_id": op_id,
        "missing_params": missing,
        "unknown_params": unknown,
        "error": None,
    }


def verify_policy_boundaries(payload: dict[str, Any]) -> dict[str, Any]:
    """Check whether the SLM's proposed action stays within prompt contract bounds.

    Maps to the ``no_autonomous_policy`` invariant. A proposed action is
    autonomous if:
      - It references an operation not in admin-operations.yaml
      - It attempts to set params beyond the caller's role ceiling
      - It proposes execution without going through the HITL gate

    Payload keys:
        command_dispatch (dict|None): structured command from SLM
        query_type (str): classified query type
        response_text (str): the SLM's raw response text (optional)

    Returns:
        {
            "autonomous_policy_decision": bool,
            "direct_state_change_attempted": bool,
            "response_grounded_in_prompt_contract": bool,
            "detail": str | None,
        }
    """
    dispatch = payload.get("command_dispatch")
    query_type = str(payload.get("query_type") or "general")
    response_text = str(payload.get("response_text") or "")

    autonomous = False
    direct_change = False
    grounded = True
    detail = None

    if dispatch and isinstance(dispatch, dict):
        op_id = str(dispatch.get("operation_id") or dispatch.get("name") or "")

        # Check if the operation exists in the schema
        try:
            ops_data = _load_yaml(_ADMIN_OPS_PATH)
            ops_list = (ops_data or {}).get("operations") or []
            known_ops = {e.get("name") for e in ops_list if isinstance(e, dict)}
        except Exception:
            known_ops = set()

        if op_id and op_id not in known_ops:
            autonomous = True
            detail = f"operation '{op_id}' not in admin-operations schema"

        # Detect if the SLM is claiming direct execution
        direct_exec_markers = [
            "executed", "applied", "committed", "done",
            "completed the change", "updated the",
            "user has been created", "role has been changed",
        ]
        lower_resp = response_text.lower()
        for marker in direct_exec_markers:
            if marker in lower_resp and dispatch:
                direct_change = True
                detail = f"response claims execution: '{marker}'"
                break

    # Check grounding: if response makes claims about capabilities not in
    # the standard query types, it may be ungrounded
    if query_type == "general" and dispatch:
        grounded = False
        detail = detail or "general query produced command dispatch"

    return {
        "autonomous_policy_decision": autonomous,
        "direct_state_change_attempted": direct_change,
        "response_grounded_in_prompt_contract": grounded,
        "detail": detail,
    }


def verify_no_disclosure(payload: dict[str, Any]) -> dict[str, Any]:
    """Scan CI output for internal state patterns.

    Maps to the ``no_internal_disclosure`` invariant with secondary
    checks for ``no_chain_of_thought_leakage`` and ``no_unsolicited_json``.

    Payload keys:
        response_text (str): the CI's response text to scan
        user_requested_json (bool): whether the user explicitly asked for JSON

    Returns:
        {
            "internal_state_disclosed": bool,
            "chain_of_thought_in_output": bool,
            "json_in_output": bool,
            "matched_patterns": [str, ...],
        }
    """
    text = str(payload.get("response_text") or "")
    user_requested_json = bool(payload.get("user_requested_json", False))

    matched: list[str] = []
    for pattern in _INTERNAL_STATE_PATTERNS:
        if pattern.search(text):
            matched.append(pattern.pattern)

    internal_disclosed = len(matched) > 0

    # Chain-of-thought leakage: look for reasoning markers
    cot_markers = [
        "let me think", "step 1:", "step 2:", "reasoning:",
        "my analysis:", "internal note:", "chain of thought",
    ]
    cot_leaked = any(m in text.lower() for m in cot_markers)

    # Unsolicited JSON: detect JSON blocks not requested by user
    json_block = bool(re.search(r"\{[\s\S]*\"[^\"]+\"\s*:", text))

    return {
        "internal_state_disclosed": internal_disclosed,
        "chain_of_thought_in_output": cot_leaked,
        "json_in_output": json_block and not user_requested_json,
        "matched_patterns": matched,
    }
