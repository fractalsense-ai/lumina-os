"""housekeeper.py — Background document indexing for the MiniLM retrieval layer.

Walks ``docs/`` trees (root and every ``domain-packs/*/docs/``), domain-physics
files, and standards — then indexes all discoverable content
into a :class:`VectorStore`.  Content-hash dedup ensures unchanged files are
not re-embedded.

The housekeeper can run in two modes:

* **Foreground full reindex** -- called by the daemon batch scheduler or
  manually via ``housekeeper_full_reindex()``.
* **Incremental poll** — called by the ResourceMonitorDaemon's idle-dispatch
  loop via ``housekeeper_incremental()``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from lumina.retrieval.embedder import DocEmbedder, DocChunk, chunk_markdown, chunk_json
from lumina.retrieval.vector_store import VectorStore, VectorStoreRegistry

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


def discover_structured_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    """Discover JSON/YAML files from standards and domain-physics."""
    files: list[Path] = []

    # Top-level directories that contain indexable structured content
    for subdir in ("standards",):
        d = repo_root / subdir
        if d.is_dir():
            files.extend(sorted(d.rglob("*.json")))
            files.extend(sorted(d.rglob("*.yaml")))

    # Domain-physics files from domain-packs
    packs = repo_root / "domain-packs"
    if packs.is_dir():
        for pack in sorted(packs.iterdir()):
            if not pack.is_dir():
                continue
            # domain-physics JSON in modules/*/
            modules_dir = pack / "modules"
            if modules_dir.is_dir():
                files.extend(sorted(modules_dir.rglob("domain-physics.json")))
            # cfg/ directory in each domain pack
            pack_cfg = pack / "cfg"
            if pack_cfg.is_dir():
                files.extend(sorted(pack_cfg.rglob("*.yaml")))
                files.extend(sorted(pack_cfg.rglob("*.json")))

    return files


# ── Domain-scoped discovery ──────────────────────────────────

def discover_domain_packs(repo_root: Path = REPO_ROOT) -> list[str]:
    """Return sorted list of domain-pack names that exist on disk."""
    packs_dir = repo_root / "domain-packs"
    if not packs_dir.is_dir():
        return []
    return sorted(d.name for d in packs_dir.iterdir() if d.is_dir())


def discover_domain_files(
    domain_id: str,
    repo_root: Path = REPO_ROOT,
) -> tuple[list[Path], list[Path]]:
    """Discover Markdown and structured files scoped to a single domain pack.

    Returns ``(md_files, structured_files)``.
    """
    pack_root = repo_root / "domain-packs" / domain_id
    md_files: list[Path] = []
    structured: list[Path] = []

    if not pack_root.is_dir():
        return md_files, structured

    # Markdown: docs/ tree inside the domain pack
    docs = pack_root / "docs"
    if docs.is_dir():
        md_files.extend(sorted(docs.rglob("*.md")))

    # Domain-lib specs (markdown)
    dlib = pack_root / "domain-lib"
    if dlib.is_dir():
        md_files.extend(sorted(dlib.rglob("*.md")))

    # Structured: domain-physics files, cfg/, glossaries
    modules = pack_root / "modules"
    if modules.is_dir():
        structured.extend(sorted(modules.rglob("domain-physics.json")))
        structured.extend(sorted(modules.rglob("glossary*.yaml")))
        structured.extend(sorted(modules.rglob("glossary*.json")))

    cfg = pack_root / "cfg"
    if cfg.is_dir():
        structured.extend(sorted(cfg.rglob("*.yaml")))
        structured.extend(sorted(cfg.rglob("*.json")))

    return md_files, structured


def discover_global_files(repo_root: Path = REPO_ROOT) -> tuple[list[Path], list[Path]]:
    """Discover Markdown and structured files outside domain packs (global scope).

    Returns ``(md_files, structured_files)``.
    """
    md_files: list[Path] = []
    root_docs = repo_root / "docs"
    if root_docs.is_dir():
        md_files.extend(sorted(root_docs.rglob("*.md")))

    structured: list[Path] = []
    for subdir in ("standards",):
        d = repo_root / subdir
        if d.is_dir():
            structured.extend(sorted(d.rglob("*.json")))
            structured.extend(sorted(d.rglob("*.yaml")))
    return md_files, structured


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

        # Structured files: JSON/YAML (physics, schemas, standards)
        structured_files = discover_structured_files(self._repo_root)
        for sf in structured_files:
            rel = sf.relative_to(self._repo_root).as_posix()
            all_chunks.extend(self._chunk_structured_file(sf, rel))

        if all_chunks:
            vectors = self._embedder.embed_chunks(all_chunks)
            self._store.add(all_chunks, vectors)
            self._store.save()

        elapsed = time.monotonic() - start
        summary = {
            "mode": "full_reindex",
            "doc_files": len(md_files),
            "structured_files": len(structured_files),
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

        # Structured files: JSON/YAML
        structured_files = discover_structured_files(self._repo_root)
        for sf in structured_files:
            rel = sf.relative_to(self._repo_root).as_posix()
            chunks = self._chunk_structured_file(sf, rel)
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
            "structured_files": len(structured_files),
            "new_chunks": len(new_chunks),
            "skipped_chunks": skipped,
            "total_stored": self._store.size,
            "elapsed_seconds": round(elapsed, 2),
        }
        log.info("Housekeeper incremental: %s", summary)
        return summary

    @staticmethod
    def _chunk_structured_file(path: Path, rel: str) -> list[DocChunk]:
        """Parse and chunk a JSON or YAML file."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix == ".json":
                data = json.loads(text)
            else:
                # YAML — use safe loader
                import yaml
                data = yaml.safe_load(text)
            if isinstance(data, dict):
                content_type = "physics" if "domain-physics" in path.name else "schema"
                return chunk_json(data, source_path=rel, content_type=content_type)
        except Exception:
            log.debug("Housekeeper: skipping unparseable structured file: %s", rel)
        return []


# ── Convenience constructors ─────────────────────────────────

_DEFAULT_STORE_DIR = REPO_ROOT / "data" / "retrieval-index"


def make_housekeeper(
    store_dir: Path = _DEFAULT_STORE_DIR,
    repo_root: Path = REPO_ROOT,
) -> Housekeeper:
    """Build a Housekeeper with default store location."""
    store = VectorStore(store_dir)
    return Housekeeper(store=store, repo_root=repo_root)


# ── Per-domain rebuild helpers ───────────────────────────────

def _chunk_files(
    md_files: list[Path],
    structured_files: list[Path],
    repo_root: Path,
    domain_id: str,
) -> list[DocChunk]:
    """Chunk markdown and structured files, tagging with *domain_id*."""
    chunks: list[DocChunk] = []
    for md_path in md_files:
        rel = md_path.relative_to(repo_root).as_posix()
        text = md_path.read_text(encoding="utf-8", errors="replace")
        for c in chunk_markdown(text, source_path=rel):
            chunks.append(DocChunk(
                source_path=c.source_path,
                heading=c.heading,
                text=c.text,
                content_hash=c.content_hash,
                content_type=c.content_type,
                domain_id=domain_id,
            ))
    for sf in structured_files:
        rel = sf.relative_to(repo_root).as_posix()
        for c in Housekeeper._chunk_structured_file(sf, rel):
            chunks.append(DocChunk(
                source_path=c.source_path,
                heading=c.heading,
                text=c.text,
                content_hash=c.content_hash,
                content_type=c.content_type,
                domain_id=domain_id,
            ))
    return chunks


def rebuild_domain_index(
    domain_id: str,
    registry: VectorStoreRegistry,
    embedder: DocEmbedder | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Clear and re-embed all content for a single domain pack.

    Returns a summary dict.
    """
    start = time.monotonic()
    embedder = embedder or DocEmbedder()
    store = registry.get(domain_id)
    store.clear()

    md_files, structured = discover_domain_files(domain_id, repo_root)
    chunks = _chunk_files(md_files, structured, repo_root, domain_id)

    if chunks:
        vectors = embedder.embed_chunks(chunks)
        store.add(chunks, vectors)
        store.save()

    elapsed = time.monotonic() - start
    summary = {
        "domain_id": domain_id,
        "mode": "domain_reindex",
        "doc_files": len(md_files),
        "structured_files": len(structured),
        "chunks_indexed": len(chunks),
        "elapsed_seconds": round(elapsed, 2),
    }
    log.info("rebuild_domain_index(%s): %s", domain_id, summary)
    return summary


def rebuild_global_index(
    registry: VectorStoreRegistry,
    embedder: DocEmbedder | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Rebuild the ``_global`` store from root-level docs/standards."""
    start = time.monotonic()
    embedder = embedder or DocEmbedder()
    store = registry.global_store
    store.clear()

    md_files, structured = discover_global_files(repo_root)
    chunks = _chunk_files(md_files, structured, repo_root, VectorStoreRegistry.GLOBAL_DOMAIN)

    if chunks:
        vectors = embedder.embed_chunks(chunks)
        store.add(chunks, vectors)
        store.save()

    elapsed = time.monotonic() - start
    summary = {
        "domain_id": VectorStoreRegistry.GLOBAL_DOMAIN,
        "mode": "global_reindex",
        "doc_files": len(md_files),
        "structured_files": len(structured),
        "chunks_indexed": len(chunks),
        "elapsed_seconds": round(elapsed, 2),
    }
    log.info("rebuild_global_index: %s", summary)
    return summary


def rebuild_all_domain_indexes(
    registry: VectorStoreRegistry,
    embedder: DocEmbedder | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Rebuild every domain store plus the global store.

    This replaces the old single-store ``full_reindex`` for the per-domain
    layout.
    """
    start = time.monotonic()
    embedder = embedder or DocEmbedder()

    domain_ids = discover_domain_packs(repo_root)
    results: list[dict[str, Any]] = []

    for did in domain_ids:
        results.append(rebuild_domain_index(did, registry, embedder, repo_root))

    results.append(rebuild_global_index(registry, embedder, repo_root))

    elapsed = time.monotonic() - start
    total_chunks = sum(r["chunks_indexed"] for r in results)
    return {
        "mode": "full_reindex_per_domain",
        "domains_rebuilt": len(domain_ids),
        "total_chunks": total_chunks,
        "elapsed_seconds": round(elapsed, 2),
        "details": results,
    }


def rebuild_group_library_dependents(
    library_id: str,
    registry: VectorStoreRegistry,
    embedder: DocEmbedder | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Rebuild only domain stores that reference the given group library.

    Scans each domain pack's physics files for ``group_libraries`` entries
    whose ``id`` matches *library_id*.  Only those domains are re-indexed.
    """
    start = time.monotonic()
    embedder = embedder or DocEmbedder()
    affected: list[str] = []

    for domain_id in discover_domain_packs(repo_root):
        pack_root = repo_root / "domain-packs" / domain_id / "modules"
        if not pack_root.is_dir():
            continue
        for physics_path in pack_root.rglob("domain-physics.json"):
            try:
                text = physics_path.read_text(encoding="utf-8")
                data = json.loads(text)
                for lib in data.get("group_libraries", []):
                    if lib.get("id") == library_id:
                        affected.append(domain_id)
                        break
            except Exception:
                continue
            if domain_id in affected:
                break

    results = []
    for did in affected:
        results.append(rebuild_domain_index(did, registry, embedder, repo_root))

    elapsed = time.monotonic() - start
    return {
        "mode": "group_library_cascade",
        "library_id": library_id,
        "affected_domains": affected,
        "total_chunks": sum(r["chunks_indexed"] for r in results),
        "elapsed_seconds": round(elapsed, 2),
        "details": results,
    }


def make_registry(
    base_dir: Path = _DEFAULT_STORE_DIR,
) -> VectorStoreRegistry:
    """Build a VectorStoreRegistry with default base location."""
    return VectorStoreRegistry(base_dir)
