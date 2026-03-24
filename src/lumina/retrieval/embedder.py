"""embedder.py — Document chunking and sentence-transformer embedding.

Chunks Markdown documents by ``## `` headers and produces 384-dimensional
embeddings using ``all-MiniLM-L6-v2`` (or a compatible model).

The model is loaded lazily on first call to :meth:`DocEmbedder.embed_chunks`
so import alone has zero startup cost.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

# ── Chunk dataclass ──────────────────────────────────────────

@dataclass(frozen=True)
class DocChunk:
    """One section of a Markdown document."""

    source_path: str
    heading: str
    text: str
    content_hash: str = field(repr=False)

    @staticmethod
    def compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Chunker ──────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^## .+", re.MULTILINE)


def chunk_markdown(text: str, source_path: str) -> list[DocChunk]:
    """Split Markdown *text* into chunks at ``## `` boundaries.

    Returns one :class:`DocChunk` per section.  Content before the first
    ``## `` heading is grouped under the heading ``(preamble)``.
    """
    splits = _HEADING_RE.split(text)
    headings = _HEADING_RE.findall(text)

    chunks: list[DocChunk] = []

    # Preamble (content before any ## heading)
    if splits and splits[0].strip():
        body = splits[0].strip()
        chunks.append(DocChunk(
            source_path=source_path,
            heading="(preamble)",
            text=body,
            content_hash=DocChunk.compute_hash(body),
        ))

    for heading, body_raw in zip(headings, splits[1:]):
        body = body_raw.strip()
        if not body:
            continue
        chunks.append(DocChunk(
            source_path=source_path,
            heading=heading.strip(),
            text=body,
            content_hash=DocChunk.compute_hash(body),
        ))

    return chunks


# ── Embedder ─────────────────────────────────────────────────

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


class DocEmbedder:
    """Embed :class:`DocChunk` text using a sentence-transformer model.

    The model is loaded lazily on first use.  Pass *model_name* to override
    the default ``all-MiniLM-L6-v2``.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self._model_name = model_name
        self._model = None  # lazy

    def _load_model(self):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self._model_name)

    def embed_texts(self, texts: list[str]) -> NDArray[np.float32]:
        """Return a ``(N, 384)`` float32 array of embeddings."""
        if self._model is None:
            self._load_model()
        vecs = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)

    def embed_chunks(self, chunks: list[DocChunk]) -> NDArray[np.float32]:
        """Embed a list of chunks, returning their vector representations."""
        texts = [f"{c.heading}\n{c.text}" for c in chunks]
        return self.embed_texts(texts)

    def embed_query(self, query: str) -> NDArray[np.float32]:
        """Embed a single search query, returning a ``(384,)`` vector."""
        return self.embed_texts([query])[0]
