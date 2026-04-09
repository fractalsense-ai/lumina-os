"""Tests for the MiniLM retrieval layer: embedder, vector_store, housekeeper."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from lumina.retrieval.embedder import (
    EMBEDDING_DIM,
    DocChunk,
    DocEmbedder,
    chunk_markdown,
)
from lumina.retrieval.vector_store import SearchResult, VectorStore, VectorStoreRegistry
from lumina.retrieval.housekeeper import (
    Housekeeper,
    collect_md_files,
    discover_doc_trees,
    make_housekeeper,
)


# ── Helpers ───────────────────────────────────────────────────

def _fake_encode(texts, *, convert_to_numpy=True, show_progress_bar=False):
    """Return deterministic pseudo-embeddings based on text length."""
    rng = np.random.RandomState(42)
    return rng.randn(len(texts), EMBEDDING_DIM).astype(np.float32)


def _make_mock_embedder() -> DocEmbedder:
    """Return a DocEmbedder with a mocked model that skips real loading."""
    embedder = DocEmbedder.__new__(DocEmbedder)
    embedder._model_name = "mock"
    mock_model = MagicMock()
    mock_model.encode = _fake_encode
    embedder._model = mock_model
    return embedder


# ══════════════════════════════════════════════════════════════
#  chunk_markdown
# ══════════════════════════════════════════════════════════════


class TestChunkMarkdown:
    def test_preamble_only(self):
        md = "This is a preamble with no headings."
        chunks = chunk_markdown(md, source_path="test.md")
        assert len(chunks) == 1
        assert chunks[0].heading == "(preamble)"
        assert chunks[0].source_path == "test.md"

    def test_single_section(self):
        md = "## Section One\n\nSome body text here."
        chunks = chunk_markdown(md, source_path="a.md")
        assert len(chunks) == 1
        assert chunks[0].heading == "## Section One"
        assert "body text" in chunks[0].text

    def test_preamble_and_sections(self):
        md = textwrap.dedent("""\
        Preamble content here.

        ## First

        Body of first.

        ## Second

        Body of second.
        """)
        chunks = chunk_markdown(md, source_path="multi.md")
        assert len(chunks) == 3
        assert chunks[0].heading == "(preamble)"
        assert chunks[1].heading == "## First"
        assert chunks[2].heading == "## Second"

    def test_empty_section_skipped(self):
        md = "## Has Body\n\nContent.\n\n## Empty\n\n## Also Body\n\nMore."
        chunks = chunk_markdown(md, source_path="x.md")
        headings = [c.heading for c in chunks]
        assert "## Empty" not in headings
        assert "## Has Body" in headings
        assert "## Also Body" in headings

    def test_empty_input(self):
        assert chunk_markdown("", source_path="empty.md") == []

    def test_content_hash_deterministic(self):
        md = "## Heading\n\nSame content."
        c1 = chunk_markdown(md, source_path="a.md")
        c2 = chunk_markdown(md, source_path="b.md")
        assert c1[0].content_hash == c2[0].content_hash

    def test_content_hash_differs_for_different_text(self):
        c1 = chunk_markdown("## H\n\nAlpha", source_path="a.md")
        c2 = chunk_markdown("## H\n\nBeta", source_path="a.md")
        assert c1[0].content_hash != c2[0].content_hash

    def test_h3_not_split(self):
        md = "## Top\n\nBody.\n\n### Sub\n\nMore body."
        chunks = chunk_markdown(md, source_path="x.md")
        assert len(chunks) == 1
        assert "### Sub" in chunks[0].text


# ══════════════════════════════════════════════════════════════
#  DocEmbedder
# ══════════════════════════════════════════════════════════════


class TestDocEmbedder:
    def test_embed_texts_shape(self):
        embedder = _make_mock_embedder()
        vecs = embedder.embed_texts(["hello world", "foo bar"])
        assert vecs.shape == (2, EMBEDDING_DIM)
        assert vecs.dtype == np.float32

    def test_embed_query_shape(self):
        embedder = _make_mock_embedder()
        vec = embedder.embed_query("some query")
        assert vec.shape == (EMBEDDING_DIM,)

    def test_embed_chunks(self):
        embedder = _make_mock_embedder()
        chunks = chunk_markdown("## A\n\nBody A.\n\n## B\n\nBody B.", source_path="t.md")
        vecs = embedder.embed_chunks(chunks)
        assert vecs.shape[0] == len(chunks)
        assert vecs.shape[1] == EMBEDDING_DIM

    def test_lazy_model_loading(self):
        embedder = DocEmbedder("all-MiniLM-L6-v2")
        assert embedder._model is None  # not loaded yet

    def test_load_model_on_first_use(self):
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.encode = _fake_encode
        mock_cls.return_value = mock_instance

        # Inject a fake sentence_transformers module so the lazy import works
        import sys
        fake_mod = MagicMock()
        fake_mod.SentenceTransformer = mock_cls
        sys.modules["sentence_transformers"] = fake_mod
        try:
            embedder = DocEmbedder("all-MiniLM-L6-v2")
            embedder.embed_texts(["test"])
            mock_cls.assert_called_once_with("all-MiniLM-L6-v2")
        finally:
            del sys.modules["sentence_transformers"]


# ══════════════════════════════════════════════════════════════
#  VectorStore
# ══════════════════════════════════════════════════════════════


class TestVectorStore:
    def test_add_and_size(self, tmp_path):
        store = VectorStore(tmp_path / "vs")
        chunks = [
            DocChunk("a.md", "## H", "body", DocChunk.compute_hash("body")),
        ]
        vecs = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        store.add(chunks, vecs)
        assert store.size == 1

    def test_clear(self, tmp_path):
        store = VectorStore(tmp_path / "vs")
        chunks = [DocChunk("a.md", "## H", "body", DocChunk.compute_hash("body"))]
        vecs = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        store.add(chunks, vecs)
        store.clear()
        assert store.size == 0

    def test_search_returns_results(self, tmp_path):
        store = VectorStore(tmp_path / "vs")
        chunks = [
            DocChunk("a.md", "## A", "alpha", DocChunk.compute_hash("alpha")),
            DocChunk("b.md", "## B", "beta", DocChunk.compute_hash("beta")),
        ]
        vecs = np.random.randn(2, EMBEDDING_DIM).astype(np.float32)
        store.add(chunks, vecs)

        query = np.random.randn(EMBEDDING_DIM).astype(np.float32)
        results = store.search(query, k=2)
        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        # scores are descending
        assert results[0].score >= results[1].score

    def test_search_k_larger_than_store(self, tmp_path):
        store = VectorStore(tmp_path / "vs")
        chunks = [DocChunk("a.md", "## A", "alpha", DocChunk.compute_hash("alpha"))]
        vecs = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        store.add(chunks, vecs)
        results = store.search(np.random.randn(EMBEDDING_DIM).astype(np.float32), k=10)
        assert len(results) == 1

    def test_search_empty_store(self, tmp_path):
        store = VectorStore(tmp_path / "vs")
        results = store.search(np.random.randn(EMBEDDING_DIM).astype(np.float32))
        assert results == []

    def test_save_load_roundtrip(self, tmp_path):
        store_dir = tmp_path / "vs"
        store = VectorStore(store_dir)
        chunks = [
            DocChunk("a.md", "## H", "body", DocChunk.compute_hash("body")),
            DocChunk("b.md", "## H2", "other", DocChunk.compute_hash("other")),
        ]
        vecs = np.random.randn(2, EMBEDDING_DIM).astype(np.float32)
        store.add(chunks, vecs)
        store.save()

        store2 = VectorStore(store_dir)
        store2.load()
        assert store2.size == 2
        assert store2._chunks[0].source_path == "a.md"
        assert store2._chunks[1].text == "other"
        np.testing.assert_array_almost_equal(store2._vectors, vecs)

    def test_has_hash(self, tmp_path):
        store = VectorStore(tmp_path / "vs")
        h = DocChunk.compute_hash("unique body")
        chunks = [DocChunk("a.md", "## H", "unique body", h)]
        vecs = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        store.add(chunks, vecs)
        assert store.has_hash(h) is True
        assert store.has_hash("nonexistent") is False

    def test_add_mismatched_lengths_raises(self, tmp_path):
        store = VectorStore(tmp_path / "vs")
        chunks = [DocChunk("a.md", "## H", "body", DocChunk.compute_hash("body"))]
        vecs = np.random.randn(2, EMBEDDING_DIM).astype(np.float32)
        with pytest.raises(ValueError, match="same length"):
            store.add(chunks, vecs)

    def test_add_wrong_dim_raises(self, tmp_path):
        store = VectorStore(tmp_path / "vs")
        chunks = [DocChunk("a.md", "## H", "body", DocChunk.compute_hash("body"))]
        vecs = np.random.randn(1, 128).astype(np.float32)
        with pytest.raises(ValueError):
            store.add(chunks, vecs)

    def test_load_no_persisted_data(self, tmp_path):
        store = VectorStore(tmp_path / "empty")
        store.load()  # should not raise
        assert store.size == 0


# ══════════════════════════════════════════════════════════════
#  Housekeeper
# ══════════════════════════════════════════════════════════════


class TestDiscoverDocTrees:
    def test_root_docs(self, tmp_path):
        (tmp_path / "docs").mkdir()
        trees = discover_doc_trees(tmp_path)
        assert tmp_path / "docs" in trees

    def test_domain_pack_docs(self, tmp_path):
        (tmp_path / "docs").mkdir()
        pack = tmp_path / "domain-packs" / "test-pack" / "docs"
        pack.mkdir(parents=True)
        trees = discover_doc_trees(tmp_path)
        assert pack in trees

    def test_no_docs_dir(self, tmp_path):
        trees = discover_doc_trees(tmp_path)
        assert trees == []


class TestCollectMdFiles:
    def test_collects_md_recursively(self, tmp_path):
        d = tmp_path / "docs"
        d.mkdir()
        (d / "README.md").write_text("# Root")
        sub = d / "1-commands"
        sub.mkdir()
        (sub / "cmd.md").write_text("# Cmd")
        (d / "notes.txt").write_text("not md")

        files = collect_md_files([d])
        names = {f.name for f in files}
        assert "README.md" in names
        assert "cmd.md" in names
        assert "notes.txt" not in names


class TestHousekeeper:
    def _setup_repo(self, tmp_path):
        """Create a minimal repo tree with two .md files."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "README.md").write_text("# Root\n\n## Overview\n\nRoot overview text.")
        pack = tmp_path / "domain-packs" / "edu" / "docs"
        pack.mkdir(parents=True)
        (pack / "guide.md").write_text("## Getting Started\n\nWelcome to the guide.")
        return tmp_path

    def test_full_reindex(self, tmp_path):
        repo = self._setup_repo(tmp_path)
        store = VectorStore(tmp_path / "store")
        embedder = _make_mock_embedder()
        hk = Housekeeper(store=store, embedder=embedder, repo_root=repo)

        summary = hk.full_reindex()
        assert summary["mode"] == "full_reindex"
        assert summary["doc_files"] == 2
        assert summary["chunks_indexed"] > 0
        assert store.size > 0

    def test_full_reindex_clears_old_data(self, tmp_path):
        repo = self._setup_repo(tmp_path)
        store = VectorStore(tmp_path / "store")
        embedder = _make_mock_embedder()
        hk = Housekeeper(store=store, embedder=embedder, repo_root=repo)

        hk.full_reindex()
        first_size = store.size
        hk.full_reindex()
        assert store.size == first_size  # cleared + re-added, same count

    def test_incremental_skips_unchanged(self, tmp_path):
        repo = self._setup_repo(tmp_path)
        store = VectorStore(tmp_path / "store")
        embedder = _make_mock_embedder()
        hk = Housekeeper(store=store, embedder=embedder, repo_root=repo)

        hk.full_reindex()
        store.save()

        summary = hk.incremental()
        assert summary["mode"] == "incremental"
        assert summary["new_chunks"] == 0
        assert summary["skipped_chunks"] > 0

    def test_incremental_detects_new_content(self, tmp_path):
        repo = self._setup_repo(tmp_path)
        store = VectorStore(tmp_path / "store")
        embedder = _make_mock_embedder()
        hk = Housekeeper(store=store, embedder=embedder, repo_root=repo)

        hk.full_reindex()
        store.save()

        # Add a new document
        (repo / "docs" / "new.md").write_text("## Fresh\n\nBrand new content.")
        summary = hk.incremental()
        assert summary["new_chunks"] >= 1

    def test_make_housekeeper_factory(self, tmp_path):
        hk = make_housekeeper(store_dir=tmp_path / "store", repo_root=tmp_path)
        assert isinstance(hk, Housekeeper)


# ══════════════════════════════════════════════════════════════
#  Night-cycle task registration
# ══════════════════════════════════════════════════════════════


class TestHousekeeperNightCycleTask:
    def test_registered(self):
        from lumina.daemon.tasks import get_cross_domain_task
        task = get_cross_domain_task("housekeeper_full_reindex")
        assert task is not None

    def test_listed(self):
        from lumina.daemon.tasks import list_cross_domain_tasks
        names = list_cross_domain_tasks()
        assert "housekeeper_full_reindex" in names

    @patch("lumina.retrieval.housekeeper.rebuild_all_domain_indexes")
    @patch("lumina.retrieval.housekeeper.make_registry")
    def test_runs_full_reindex(self, mock_make_reg, mock_rebuild):
        from lumina.daemon.tasks import get_cross_domain_task

        mock_registry = MagicMock()
        mock_make_reg.return_value = mock_registry
        mock_rebuild.return_value = {
            "mode": "full_reindex_per_domain",
            "domains_rebuilt": 2,
            "total_chunks": 20,
            "elapsed_seconds": 1.23,
        }

        task_fn = get_cross_domain_task("housekeeper_full_reindex")
        result = task_fn(domains=[{"domain_id": "test"}])
        assert result.success is True
        assert result.task == "housekeeper_full_reindex"
        mock_rebuild.assert_called_once_with(mock_registry)

    @patch("lumina.retrieval.housekeeper.make_registry")
    def test_handles_failure_gracefully(self, mock_make_reg):
        from lumina.daemon.tasks import get_cross_domain_task

        mock_make_reg.side_effect = RuntimeError("model not found")

        task_fn = get_cross_domain_task("housekeeper_full_reindex")
        result = task_fn(domains=[])
        assert result.success is False
        assert "error" in result.metadata


# ══════════════════════════════════════════════════════════════
#  VectorStoreRegistry
# ══════════════════════════════════════════════════════════════


class TestVectorStoreRegistry:
    def test_get_creates_store(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        store = registry.get("edu")
        assert isinstance(store, VectorStore)

    def test_get_returns_same(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        assert registry.get("edu") is registry.get("edu")

    def test_global_store_shortcut(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        assert registry.global_store is registry.get(VectorStoreRegistry.GLOBAL_DOMAIN)

    def test_domain_ids_reflects_persisted(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        assert registry.domain_ids() == []
        # Persist one store
        store = registry.get("test")
        vec = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        chunk = DocChunk("x.md", "h", "t", "h1", "doc", "test")
        store.add([chunk], vec)
        store.save()
        assert "test" in registry.domain_ids()

    def test_stores_are_isolated(self, tmp_path: Path):
        registry = VectorStoreRegistry(tmp_path)
        sa = registry.get("a")
        sb = registry.get("b")
        vec = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        chunk = DocChunk("x.md", "h", "t", "h1", "doc", "a")
        sa.add([chunk], vec)
        assert sa.size == 1
        assert sb.size == 0
