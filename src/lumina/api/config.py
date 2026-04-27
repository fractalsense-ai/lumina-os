"""Centralized configuration, singletons, and environment parsing."""

from __future__ import annotations

import copy
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
# ── Local / self-hosted (Ollama, vLLM, LM Studio, TGI, OpenRouter) ──────────
LLM_MODEL = os.environ.get("LUMINA_LLM_MODEL", "llama3")
LLM_ENDPOINT = os.environ.get("LUMINA_LLM_ENDPOINT", "http://localhost:11434")
LLM_TIMEOUT = float(os.environ.get("LUMINA_LLM_TIMEOUT", "120"))
# ── Google Gemini ─────────────────────────────────────────────────────────────
GOOGLE_MODEL = os.environ.get("LUMINA_GOOGLE_MODEL", "gemini-2.0-flash")
# ── Azure OpenAI ─────────────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.environ.get("LUMINA_AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("LUMINA_AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_VERSION = os.environ.get("LUMINA_AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
# ── Mistral AI ────────────────────────────────────────────────────────────────
MISTRAL_MODEL = os.environ.get("LUMINA_MISTRAL_MODEL", "mistral-large-latest")
# ── Embedding model (MiniLM via Ollama or HuggingFace sentence-transformers) ─
EMBEDDING_PROVIDER = os.environ.get("LUMINA_EMBEDDING_PROVIDER", "ollama")
EMBEDDING_MODEL = os.environ.get("LUMINA_EMBEDDING_MODEL", "all-minilm")
EMBEDDING_ENDPOINT = os.environ.get("LUMINA_EMBEDDING_ENDPOINT", "http://localhost:11434")
EMBEDDING_TIMEOUT = float(os.environ.get("LUMINA_EMBEDDING_TIMEOUT", "30"))
RUNTIME_CONFIG_PATH = os.environ.get("LUMINA_RUNTIME_CONFIG_PATH")
_explicit_registry = os.environ.get("LUMINA_DOMAIN_REGISTRY_PATH")
DOMAIN_REGISTRY_PATH: str | None = (
    _explicit_registry
    if _explicit_registry
    else (None if RUNTIME_CONFIG_PATH else "model-packs/system/cfg/domain-registry.yaml")
)
PERSISTENCE_BACKEND = os.environ.get("LUMINA_PERSISTENCE_BACKEND", "filesystem").strip().lower()
DB_URL = os.environ.get("LUMINA_DB_URL")
ENFORCE_POLICY_COMMITMENT = os.environ.get("LUMINA_ENFORCE_POLICY_COMMITMENT", "true").strip().lower() not in {"0", "false", "no"}

_SYSTEM_PHYSICS_PATH = Path(os.environ.get("LUMINA_SYSTEM_PHYSICS_PATH", str(_REPO_ROOT / "model-packs" / "system" / "cfg" / "system-physics.json")))
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

_DEFAULT_LOG_DIR = Path(tempfile.gettempdir()) / "lumina-log"
# Backward compat: honour legacy LUMINA_CTL_DIR if LUMINA_LOG_DIR is not set
LOG_DIR = Path(os.environ.get("LUMINA_LOG_DIR", os.environ.get("LUMINA_CTL_DIR", str(_DEFAULT_LOG_DIR))))
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _build_persistence_adapter() -> PersistenceAdapter:
    if PERSISTENCE_BACKEND == "sqlite":
        from lumina.persistence.sqlite import SQLitePersistenceAdapter
        return SQLitePersistenceAdapter(repo_root=_REPO_ROOT, database_url=DB_URL)
    return FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, log_dir=LOG_DIR)


PERSISTENCE: PersistenceAdapter = _build_persistence_adapter()

# ─────────────────────────────────────────────────────────────
# Per-user profile helpers
# ─────────────────────────────────────────────────────────────

_PROFILES_DIR = _REPO_ROOT / "data" / "profiles"


def _resolve_user_profile_path(user_id: str, domain_key: str) -> Path:
    """Return ``data/profiles/{user_id}/{domain_key}.yaml`` under the repo root."""
    safe_uid = user_id.replace("/", "_").replace("\\", "_")
    safe_domain = domain_key.replace("/", "_").replace("\\", "_")
    return _PROFILES_DIR / safe_uid / f"{safe_domain}.yaml"


# ── Default system-role → domain-role mapping ───────────────
# Generic fallback used when the JWT has no explicit domain_roles claim
# and the domain pack does not provide its own ``system_role_to_domain_role``
# mapping in its manifest.  Domain packs should override this via their
# pack.yaml or runtime-config.yaml ``system_role_to_domain_role`` key.
_SYSTEM_ROLE_TO_DOMAIN_ROLE: dict[str, str] = {
    "root": "admin",
    "admin": "admin",
    "super_admin": "operator",
    "operator": "participant",
    "half_operator": "observer",
    "user": "participant",
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into a copy of *base*.

    Scalar values in *overlay* overwrite *base*.  Dicts are merged
    recursively.  Lists in *overlay* replace those in *base*.
    """
    result = copy.deepcopy(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def _assemble_profile(
    base_path: str | None,
    domain_ext_path: str | None,
    role_ext_path: str | None,
) -> dict[str, Any]:
    """Compose a profile dict by deep-merging Base → Domain → Role layers."""
    import yaml

    profile: dict[str, Any] = {}
    for layer_path in (base_path, domain_ext_path, role_ext_path):
        if layer_path and Path(layer_path).is_file():
            with open(layer_path, encoding="utf-8") as fh:
                layer = yaml.safe_load(fh) or {}
            profile = _deep_merge(profile, layer)
    return profile


def _ensure_user_profile(
    user_id: str,
    domain_key: str,
    template_path: str,
    *,
    runtime: dict[str, Any] | None = None,
    domain_role: str | None = None,
    system_role: str | None = None,
) -> str:
    """Return a user-specific profile path, creating from template layers if needed.

    When the runtime context provides hierarchical profile templates
    (``base_profile_path``, ``domain_profile_extension_path``,
    ``profile_templates``), the profile is assembled from three layers
    (Base → Domain → Role).  Otherwise falls back to a flat copy of
    *template_path* for backward compatibility.

    If the persistence backend supports key-based profiles, the assembled
    profile is also persisted there via ``save_profile()``.
    """
    target = _resolve_user_profile_path(user_id, domain_key)

    # Check key-based store first (DB backend)
    existing = PERSISTENCE.load_profile(user_id, domain_key)
    if existing is not None:
        # Ensure the filesystem copy also exists for path-based callers
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            import yaml
            with open(target, "w", encoding="utf-8") as fh:
                yaml.safe_dump(existing, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return str(target)

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        rt = runtime or {}
        profile_templates = rt.get("profile_templates")

        if profile_templates:
            # Resolve the effective domain role
            effective_role = domain_role
            if not effective_role and system_role:
                effective_role = _SYSTEM_ROLE_TO_DOMAIN_ROLE.get(system_role)
            role_key = effective_role or "default"
            role_ext_path = profile_templates.get(role_key) or profile_templates.get("default")

            profile = _assemble_profile(
                base_path=rt.get("base_profile_path"),
                domain_ext_path=rt.get("domain_profile_extension_path"),
                role_ext_path=role_ext_path,
            )
            import yaml
            with open(target, "w", encoding="utf-8") as fh:
                yaml.safe_dump(profile, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
            log.info(
                "Assembled profile for user=%s domain=%s role=%s at %s",
                user_id, domain_key, role_key, target,
            )
        else:
            # Backward-compatible flat copy for domains without layered templates
            import shutil
            shutil.copy2(template_path, target)
            log.info("Initialised profile for user=%s domain=%s at %s", user_id, domain_key, target)

        # Persist into key-based store so DB backend has it
        try:
            from lumina.core.yaml_loader import load_yaml
            fresh = load_yaml(str(target))
            if isinstance(fresh, dict):
                PERSISTENCE.save_profile(user_id, domain_key, fresh)
        except Exception:
            log.debug("Could not save new profile to key-based store for user=%s", user_id)

    return str(target)


def _canonical_sha256(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
