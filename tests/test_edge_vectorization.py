"""Tests for edge vectorization: VectorStoreRegistry and per-domain rebuild (Phase 3)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from lumina.retrieval.embedder import EMBEDDING_DIM, DocChunk, DocEmbedder
from lumina.retrieval.vector_store import VectorStore, VectorStoreRegistry
from lumina.retrieval.housekeeper import (
    rebuild_domain_index,
    rebuild_global_index,
    rebuild_all_domain_indexes,
    rebuild_group_library_dependents,
    make_registry,
    discover_domain_packs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_encode(texts, *, convert_to_numpy=True, show_progress_bar=False):
    """Return deterministic pseudo-embeddings based on text length."""
    rng = np.random.RandomState(42)
    return rng.randn(len(texts), EMBEDDING_DIM).astype(np.float32)


def _make_mock_embedder() -> DocEmbedder:
    embedder = DocEmbedder.__new__(DocEmbedder)
    embedder._provider = "sentence-transformers"
    embedder._model_name = "mock"
    embedder._endpoint = "http://localhost:11434"
    embedder._timeout = 30.0
    mock_model = MagicMock()
    mock_model.encode = _fake_encode
    embedder._model = mock_model
    return embedder


def _write_md(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _write_physics(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """Mini repo with 2 domain packs + root docs for rebuild tests."""
    repo = tmp_path / "repo"

    # Root docs
    _write_md(repo / "docs" / "README.md", """\
        # Root Docs
        Some global documentation content here.
    """)

    # Domain pack: edu
    _write_md(repo / "model-packs" / "edu" / "docs" / "overview.md", """\
        # Education Overview
        This domain handles educational content.
    """)
    (repo / "model-packs" / "edu" / "cfg").mkdir(parents=True, exist_ok=True)

    # Domain pack: agri — with group_libraries in physics
    _write_md(repo / "model-packs" / "agri" / "docs" / "farming.md", """\
        # Farming Docs
        Agricultural monitoring documentation.
    """)
    (repo / "model-packs" / "agri" / "cfg").mkdir(parents=True, exist_ok=True)
    _write_physics(
        repo / "model-packs" / "agri" / "modules" / "ops-1" / "domain-physics.json",
        {
            "domain_id": "agriculture/ops-1",
            "group_libraries": [
                {
                    "id": "environmental_sensors",
                    "path": "domain-lib/environmental_sensors.py",
                    "description": "Sensor helpers.",
                    "shared_with_modules": ["ops-1"],
                }
            ],
        },
    )

    return repo


# ===================================================================
# Test: VectorStoreRegistry
# ===================================================================


class TestVectorStoreRegistry:
    def test_creates_store_on_first_get(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        store = registry.get("edu")
        assert isinstance(store, VectorStore)

    def test_same_store_returned(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        s1 = registry.get("edu")
        s2 = registry.get("edu")
        assert s1 is s2

    def test_global_store_alias(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        gs = registry.global_store
        explicit = registry.get(VectorStoreRegistry.GLOBAL_DOMAIN)
        assert gs is explicit

    def test_domain_ids_empty(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        assert registry.domain_ids() == []

    def test_domain_ids_after_save(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        store = registry.get("test-domain")
        vec = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        chunk = DocChunk("test.md", "heading", "text", "hash1", "doc", "test-domain")
        store.add([chunk], vec)
        store.save()
        ids = registry.domain_ids()
        assert "test-domain" in ids

    def test_load_all(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        store = registry.get("edu")
        vec = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        chunk = DocChunk("x.md", "h", "t", "h1", "doc", "edu")
        store.add([chunk], vec)
        store.save()

        fresh = VectorStoreRegistry(tmp_path)
        fresh.load_all()
        assert fresh.get("edu").size == 1

    def test_isolation(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        store_a = registry.get("a")
        store_b = registry.get("b")
        vec = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        chunk = DocChunk("x.md", "h", "t", "h1", "doc", "a")
        store_a.add([chunk], vec)
        assert store_a.size == 1
        assert store_b.size == 0

    def test_global_domain_constant(self):
        assert VectorStoreRegistry.GLOBAL_DOMAIN == "_global"


# ===================================================================
# Test: rebuild_domain_index
# ===================================================================


class TestRebuildDomainIndex:
    def test_rebuilds_single_domain(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_domain_index("edu", registry, embedder, fake_repo)
        assert summary["domain_id"] == "edu"
        assert summary["chunks_indexed"] >= 1
        assert registry.get("edu").size >= 1

    def test_clears_before_rebuild(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        s1 = rebuild_domain_index("edu", registry, embedder, fake_repo)
        s2 = rebuild_domain_index("edu", registry, embedder, fake_repo)
        assert s1["chunks_indexed"] == s2["chunks_indexed"]

    def test_summary_structure(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_domain_index("edu", registry, embedder, fake_repo)
        for key in ("mode", "domain_id", "doc_files", "chunks_indexed", "elapsed_seconds"):
            assert key in summary

    def test_nonexistent_domain(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_domain_index("nonexistent", registry, embedder, fake_repo)
        assert summary["chunks_indexed"] == 0


# ===================================================================
# Test: rebuild_global_index
# ===================================================================


class TestRebuildGlobalIndex:
    def test_populates_global_store(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_global_index(registry, embedder, fake_repo)
        assert registry.global_store.size >= 1

    def test_summary_structure(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_global_index(registry, embedder, fake_repo)
        assert summary["mode"] == "global_reindex"
        assert summary["domain_id"] == "_global"


# ===================================================================
# Test: rebuild_all_domain_indexes
# ===================================================================


class TestRebuildAllDomainIndexes:
    def test_rebuilds_all_plus_global(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_all_domain_indexes(registry, embedder, fake_repo)
        assert summary["domains_rebuilt"] >= 2  # edu + agri
        assert len(summary["details"]) >= 3  # edu + agri + _global

    def test_total_chunks_aggregated(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_all_domain_indexes(registry, embedder, fake_repo)
        detail_sum = sum(d["chunks_indexed"] for d in summary["details"])
        assert summary["total_chunks"] == detail_sum

    def test_mode_label(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_all_domain_indexes(registry, embedder, fake_repo)
        assert summary["mode"] == "full_reindex_per_domain"


# ===================================================================
# Test: rebuild_group_library_dependents
# ===================================================================


class TestRebuildGroupLibraryDependents:
    def test_only_affected_domains_rebuilt(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_group_library_dependents(
            "environmental_sensors", registry, embedder, fake_repo,
        )
        assert "agri" in summary["affected_domains"]
        assert "edu" not in summary["affected_domains"]

    def test_no_affected_domains(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_group_library_dependents(
            "nonexistent_library", registry, embedder, fake_repo,
        )
        assert summary["affected_domains"] == []

    def test_summary_structure(self, fake_repo: Path, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path / "stores")
        embedder = _make_mock_embedder()
        summary = rebuild_group_library_dependents(
            "environmental_sensors", registry, embedder, fake_repo,
        )
        for key in ("mode", "library_id", "affected_domains"):
            assert key in summary
        assert summary["mode"] == "group_library_cascade"
        assert summary["library_id"] == "environmental_sensors"
