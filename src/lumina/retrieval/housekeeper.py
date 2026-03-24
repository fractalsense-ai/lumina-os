"""housekeeper.py — Background document indexing for the MiniLM retrieval layer.

Walks ``docs/`` trees (root and every ``domain-packs/*/docs/``) and indexes
all ``.md`` files into a :class:`VectorStore`.  Content-hash dedup ensures
unchanged files are not re-embedded.

The housekeeper can run in two modes:

* **Foreground full reindex** — called by the night-cycle scheduler or
  manually via ``housekeeper_full_reindex()``.
* **Incremental poll** — called by the ResourceMonitorDaemon's idle-dispatch
  loop via ``housekeeper_incremental()``.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any

from lumina.retrieval.embedder import DocEmbedder, DocChunk, chunk_markdown
from lumina.retrieval.vector_store import VectorStore

log = logging.getLogger("lumina-retrieval")

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── Discovery ────────────────────────────────────────────────

def discover_doc_trees(repo_root: Path = REPO_ROOT) -> list[Path]:
    """Return all ``docs/`` directories: root + every domain pack."""
    trees: list[Path] = []
    root_docs = repo_root / "docs"
    if root_docs.is_dir():
        trees.append(root_docs)
    packs = repo_root / "domain-packs"
    if packs.is_dir():
        for pack in sorted(packs.iterdir()):
            pack_docs = pack / "docs"
            if pack_docs.is_dir():
                trees.append(pack_docs)
    return trees


def collect_md_files(trees: list[Path]) -> list[Path]:
    """Recursively collect all ``.md`` files from *trees*."""
    files: list[Path] = []
    for tree in trees:
        files.extend(sorted(tree.rglob("*.md")))
    return files


# ── Housekeeper core ─────────────────────────────────────────

class Housekeeper:
    """Indexes Markdown documents into a VectorStore with dedup.

    Parameters
    ----------
    store:
        Persistent vector store.
    embedder:
        Sentence-transformer embedder.
    repo_root:
        Workspace root for discovering ``docs/`` trees.
    """

    def __init__(
        self,
        store: VectorStore,
        embedder: DocEmbedder | None = None,
        repo_root: Path = REPO_ROOT,
    ) -> None:
        self._store = store
        self._embedder = embedder or DocEmbedder()
        self._repo_root = repo_root

    def full_reindex(self) -> dict[str, Any]:
        """Clear the store and re-embed every document.

        Returns a summary dict with counts.
        """
        start = time.monotonic()
        self._store.clear()

        trees = discover_doc_trees(self._repo_root)
        md_files = collect_md_files(trees)

        all_chunks: list[DocChunk] = []
        for md_path in md_files:
            rel = md_path.relative_to(self._repo_root).as_posix()
            text = md_path.read_text(encoding="utf-8", errors="replace")
            all_chunks.extend(chunk_markdown(text, source_path=rel))

        if all_chunks:
            vectors = self._embedder.embed_chunks(all_chunks)
            self._store.add(all_chunks, vectors)
            self._store.save()

        elapsed = time.monotonic() - start
        summary = {
            "mode": "full_reindex",
            "doc_files": len(md_files),
            "chunks_indexed": len(all_chunks),
            "elapsed_seconds": round(elapsed, 2),
        }
        log.info("Housekeeper full reindex: %s", summary)
        return summary

    def incremental(self) -> dict[str, Any]:
        """Index only documents with new content hashes (skip unchanged).

        Returns a summary dict with counts.
        """
        start = time.monotonic()
        self._store.load()

        trees = discover_doc_trees(self._repo_root)
        md_files = collect_md_files(trees)

        new_chunks: list[DocChunk] = []
        skipped = 0
        for md_path in md_files:
            rel = md_path.relative_to(self._repo_root).as_posix()
            text = md_path.read_text(encoding="utf-8", errors="replace")
            chunks = chunk_markdown(text, source_path=rel)
            for c in chunks:
                if self._store.has_hash(c.content_hash):
                    skipped += 1
                else:
                    new_chunks.append(c)

        if new_chunks:
            vectors = self._embedder.embed_chunks(new_chunks)
            self._store.add(new_chunks, vectors)
            self._store.save()

        elapsed = time.monotonic() - start
        summary = {
            "mode": "incremental",
            "doc_files": len(md_files),
            "new_chunks": len(new_chunks),
            "skipped_chunks": skipped,
            "total_stored": self._store.size,
            "elapsed_seconds": round(elapsed, 2),
        }
        log.info("Housekeeper incremental: %s", summary)
        return summary


# ── Convenience constructors ─────────────────────────────────

_DEFAULT_STORE_DIR = REPO_ROOT / "data" / "retrieval-index"


def make_housekeeper(
    store_dir: Path = _DEFAULT_STORE_DIR,
    repo_root: Path = REPO_ROOT,
) -> Housekeeper:
    """Build a Housekeeper with default store location."""
    store = VectorStore(store_dir)
    return Housekeeper(store=store, repo_root=repo_root)
