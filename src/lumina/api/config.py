"""Centralized configuration, singletons, and environment parsing."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from lumina.core.domain_registry import DomainRegistry
from lumina.core.runtime_loader import load_runtime_context
from lumina.persistence.adapter import PersistenceAdapter
from lumina.persistence.filesystem import FilesystemPersistenceAdapter

log = logging.getLogger("lumina-api")

# ─────────────────────────────────────────────────────────────
# Resolve paths
# ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]

# ─────────────────────────────────────────────────────────────
# Environment-driven configuration
# ─────────────────────────────────────────────────────────────

LLM_PROVIDER = os.environ.get("LUMINA_LLM_PROVIDER", "openai")
OPENAI_MODEL = os.environ.get("LUMINA_OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL = os.environ.get("LUMINA_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
RUNTIME_CONFIG_PATH = os.environ.get("LUMINA_RUNTIME_CONFIG_PATH")
_explicit_registry = os.environ.get("LUMINA_DOMAIN_REGISTRY_PATH")
DOMAIN_REGISTRY_PATH: str | None = (
    _explicit_registry
    if _explicit_registry
    else (None if RUNTIME_CONFIG_PATH else "cfg/domain-registry.yaml")
)
PERSISTENCE_BACKEND = os.environ.get("LUMINA_PERSISTENCE_BACKEND", "filesystem").strip().lower()
DB_URL = os.environ.get("LUMINA_DB_URL")
ENFORCE_POLICY_COMMITMENT = os.environ.get("LUMINA_ENFORCE_POLICY_COMMITMENT", "true").strip().lower() not in {"0", "false", "no"}

_SYSTEM_PHYSICS_PATH = Path(os.environ.get("LUMINA_SYSTEM_PHYSICS_PATH", str(_REPO_ROOT / "cfg" / "system-physics.json")))
try:
    with open(_SYSTEM_PHYSICS_PATH, encoding="utf-8") as _fh:
        _system_physics_data = json.load(_fh)
    SYSTEM_PHYSICS_HASH: str | None = hashlib.sha256(
        json.dumps(_system_physics_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
except Exception:
    log.warning("Could not load system-physics.json from %s; system-physics gate disabled.", _SYSTEM_PHYSICS_PATH)
    SYSTEM_PHYSICS_HASH = None

CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("LUMINA_CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
BOOTSTRAP_MODE: bool = os.environ.get("LUMINA_BOOTSTRAP_MODE", "true").strip().lower() not in {"0", "false", "no"}

# Session idle timeout (minutes). 0 = disabled.
SESSION_IDLE_TIMEOUT_MINUTES: int = int(os.environ.get("LUMINA_SESSION_IDLE_TIMEOUT_MINUTES", "30"))

# ─────────────────────────────────────────────────────────────
# Domain Registry
# ─────────────────────────────────────────────────────────────

DOMAIN_REGISTRY = DomainRegistry(
    repo_root=_REPO_ROOT,
    registry_path=DOMAIN_REGISTRY_PATH,
    single_config_path=RUNTIME_CONFIG_PATH,
    load_runtime_context_fn=load_runtime_context,
)

# ─────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────

_DEFAULT_CTL_DIR = Path(tempfile.gettempdir()) / "lumina-ctl"
CTL_DIR = Path(os.environ.get("LUMINA_CTL_DIR", str(_DEFAULT_CTL_DIR)))
CTL_DIR.mkdir(parents=True, exist_ok=True)


def _build_persistence_adapter() -> PersistenceAdapter:
    if PERSISTENCE_BACKEND == "sqlite":
        from lumina.persistence.sqlite import SQLitePersistenceAdapter
        return SQLitePersistenceAdapter(repo_root=_REPO_ROOT, database_url=DB_URL)
    return FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, ctl_dir=CTL_DIR)


PERSISTENCE: PersistenceAdapter = _build_persistence_adapter()

# ─────────────────────────────────────────────────────────────
# Per-user profile helpers
# ─────────────────────────────────────────────────────────────

_PROFILES_DIR = _REPO_ROOT / "cfg" / "profiles"


def _resolve_user_profile_path(user_id: str, domain_key: str) -> Path:
    """Return ``cfg/profiles/{user_id}/{domain_key}.yaml`` under the repo root."""
    safe_uid = user_id.replace("/", "_").replace("\\", "_")
    safe_domain = domain_key.replace("/", "_").replace("\\", "_")
    return _PROFILES_DIR / safe_uid / f"{safe_domain}.yaml"


def _ensure_user_profile(user_id: str, domain_key: str, template_path: str) -> str:
    """Return a user-specific profile path, copying template if not yet created."""
    target = _resolve_user_profile_path(user_id, domain_key)
    if not target.exists():
        import shutil
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template_path, target)
        log.info("Initialised profile for user=%s domain=%s at %s", user_id, domain_key, target)
    return str(target)


def _canonical_sha256(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
