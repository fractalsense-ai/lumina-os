from __future__ import annotations

from lumina.core.pack_identity import (
    MODEL_PACK_ACTIVATION,
    MODEL_PACK_ROLLBACK,
    get_model_pack_id,
    get_model_pack_version,
    is_model_pack_commitment_type,
    normalize_pack_commitment_type,
)


def test_get_model_pack_identity_prefers_current_fields() -> None:
    record = {
        "model_pack_id": "domain/current/v1",
        "model_pack_version": "2.0.0",
        "domain_pack_id": "domain/legacy/v1",
        "domain_pack_version": "1.0.0",
    }

    assert get_model_pack_id(record) == "domain/current/v1"
    assert get_model_pack_version(record) == "2.0.0"


def test_get_model_pack_identity_falls_back_to_legacy_metadata() -> None:
    record = {
        "metadata": {
            "domain_pack_id": "domain/legacy/v1",
            "domain_pack_version": "1.0.0",
        }
    }

    assert get_model_pack_id(record) == "domain/legacy/v1"
    assert get_model_pack_version(record) == "1.0.0"


def test_pack_commitment_type_aliases() -> None:
    assert normalize_pack_commitment_type("domain_pack_activation") == MODEL_PACK_ACTIVATION
    assert normalize_pack_commitment_type("domain_pack_rollback") == MODEL_PACK_ROLLBACK
    assert is_model_pack_commitment_type("domain_pack_activation") is True
    assert is_model_pack_commitment_type(MODEL_PACK_ROLLBACK) is True
    assert is_model_pack_commitment_type("policy_change") is False
