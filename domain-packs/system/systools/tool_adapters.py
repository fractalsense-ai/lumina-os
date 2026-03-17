"""tool_adapters.py — Read-only system-domain tool adapters.

Each function accepts a ``payload`` dict and returns a dict result.
These are registered under ``adapters.tools`` in the system domain's
runtime-config.yaml and invoked via ``invoke_runtime_tool()`` in the
server when the command-dispatch layer resolves to a tool call.

No imports from ``lumina.api`` or ``lumina.core`` are allowed here —
adapters must be self-contained so they can be loaded and tested
independently of the server.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# Repo root is 4 parents up: systools/ → system/ → domain-packs/ → project-lumina/
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]

_DEFAULT_CTL_DIR = Path(tempfile.gettempdir()) / "lumina-ctl"
_CTL_DIR: Path = Path(os.environ.get("LUMINA_CTL_DIR", str(_DEFAULT_CTL_DIR)))

_DOMAIN_REGISTRY_PATH: Path = _REPO_ROOT / "cfg" / "domain-registry.yaml"


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


def _scan_all_ctl_records(ctl_dir: Path) -> list[dict[str, Any]]:
    """Return all CTL records across every JSONL ledger in *ctl_dir*."""
    all_records: list[dict[str, Any]] = []
    if not ctl_dir.is_dir():
        return all_records
    for ledger_path in sorted(ctl_dir.glob("session-*.jsonl")):
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
    CTL commitment record exists.  This is a read-only health check —
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

    # Scan CTL for CommitmentRecords that reference this physics hash.
    all_records = _scan_all_ctl_records(_CTL_DIR)
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
    """Return recent escalation records from the CTL.

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

    all_records = _scan_all_ctl_records(_CTL_DIR)
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


def list_ctl_records(payload: dict[str, Any]) -> dict[str, Any]:
    """Return recent CTL records across all sessions.

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

    all_records = _scan_all_ctl_records(_CTL_DIR)

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
