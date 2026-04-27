"""Model-pack identity helpers.

The repository's pack artifact layer is now called ``model-pack``. Some
historical records and fixtures still use ``domain_pack_*`` keys. Readers
should prefer the new ``model_pack_*`` keys and fall back to old keys while
this migration is in flight.
"""

from __future__ import annotations

from typing import Any, Mapping

MODEL_PACK_ACTIVATION = "model_pack_activation"
MODEL_PACK_ROLLBACK = "model_pack_rollback"
LEGACY_DOMAIN_PACK_ACTIVATION = "domain_pack_activation"
LEGACY_DOMAIN_PACK_ROLLBACK = "domain_pack_rollback"

_COMMITMENT_TYPE_ALIASES = {
    LEGACY_DOMAIN_PACK_ACTIVATION: MODEL_PACK_ACTIVATION,
    LEGACY_DOMAIN_PACK_ROLLBACK: MODEL_PACK_ROLLBACK,
}


def _clean(value: Any) -> str:
    return str(value) if value not in (None, "") else ""


def _nested_mapping(record: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = record.get(key)
    return value if isinstance(value, Mapping) else {}


def get_model_pack_id(record: Mapping[str, Any] | None) -> str:
    """Return model-pack id from a record/provenance mapping.

    Lookup order is new direct key, old direct key, new metadata key, old
    metadata key. This keeps historical System Log records readable while
    current writers move to ``model_pack_id``.
    """
    if not isinstance(record, Mapping):
        return ""
    metadata = _nested_mapping(record, "metadata")
    return (
        _clean(record.get("model_pack_id"))
        or _clean(record.get("domain_pack_id"))
        or _clean(metadata.get("model_pack_id"))
        or _clean(metadata.get("domain_pack_id"))
    )


def get_model_pack_version(record: Mapping[str, Any] | None) -> str:
    """Return model-pack version from a record/provenance mapping."""
    if not isinstance(record, Mapping):
        return ""
    metadata = _nested_mapping(record, "metadata")
    return (
        _clean(record.get("model_pack_version"))
        or _clean(record.get("domain_pack_version"))
        or _clean(metadata.get("model_pack_version"))
        or _clean(metadata.get("domain_pack_version"))
    )


def normalize_pack_commitment_type(commitment_type: Any) -> str:
    """Map legacy domain-pack commitment names to model-pack names."""
    value = _clean(commitment_type)
    return _COMMITMENT_TYPE_ALIASES.get(value, value)


def is_model_pack_commitment_type(commitment_type: Any) -> bool:
    """Return True for current or legacy model-pack lifecycle records."""
    return normalize_pack_commitment_type(commitment_type) in {
        MODEL_PACK_ACTIVATION,
        MODEL_PACK_ROLLBACK,
    }
