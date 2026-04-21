"""embedder.py — Document chunking and embedding via Ollama or sentence-transformers.

Chunks Markdown documents by ``## `` headers and produces 384-dimensional
embeddings using ``all-minilm`` (Ollama, default) or ``all-MiniLM-L6-v2``
(HuggingFace sentence-transformers fallback).

The embedding provider is selected via ``LUMINA_EMBEDDING_PROVIDER``.
The model is loaded / connected lazily on first call to
:meth:`DocEmbedder.embed_texts` so import alone has zero startup cost.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

log = logging.getLogger("lumina-embedder")

# ── Chunk dataclass ──────────────────────────────────────────

@dataclass(frozen=True)
class DocChunk:
    """One section of a document (Markdown, JSON, YAML, etc.)."""

    source_path: str
    heading: str
    text: str
    content_hash: str = field(repr=False)
    content_type: str = field(default="doc", repr=False)
    domain_id: str = field(default="", repr=False)

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


def chunk_json(data: dict, source_path: str, *, content_type: str = "schema") -> list[DocChunk]:
    """Chunk a JSON/YAML dict into embeddable sections.

    Extracts top-level keys as headings and their stringified values as text.
    Nested lists (e.g. glossary entries, modules) each become their own chunk.
    """
    chunks: list[DocChunk] = []
    for key, value in data.items():
        if isinstance(value, list):
            for i, item in enumerate(value):
                body = json.dumps(item, ensure_ascii=False, indent=1) if isinstance(item, dict) else str(item)
                if not body.strip():
                    continue
                heading = f"{key}[{i}]"
                chunks.append(DocChunk(
                    source_path=source_path,
                    heading=heading,
                    text=body,
                    content_hash=DocChunk.compute_hash(body),
                    content_type=content_type,
                ))
        elif isinstance(value, dict):
            body = json.dumps(value, ensure_ascii=False, indent=1)
            if body.strip():
                chunks.append(DocChunk(
                    source_path=source_path,
                    heading=key,
                    text=body,
                    content_hash=DocChunk.compute_hash(body),
                    content_type=content_type,
                ))
        else:
            body = str(value).strip()
            if body:
                chunks.append(DocChunk(
                    source_path=source_path,
                    heading=key,
                    text=body,
                    content_hash=DocChunk.compute_hash(body),
                    content_type=content_type,
                ))
    return chunks


# ── Embedder ─────────────────────────────────────────────────

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# Provider constants
PROVIDER_OLLAMA = "ollama"
PROVIDER_SENTENCE_TRANSFORMERS = "sentence-transformers"


def _resolve_config():
    """Read embedding config from lumina.api.config (deferred to avoid circular imports)."""
    try:
        from lumina.api.config import (
            EMBEDDING_PROVIDER,
            EMBEDDING_MODEL,
            EMBEDDING_ENDPOINT,
            EMBEDDING_TIMEOUT,
        )
        return EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_ENDPOINT, EMBEDDING_TIMEOUT
    except ImportError:
        return PROVIDER_OLLAMA, "all-minilm", "http://localhost:11434", 30.0


class DocEmbedder:
    """Embed :class:`DocChunk` text using Ollama or sentence-transformers.

    The provider is selected via ``LUMINA_EMBEDDING_PROVIDER`` (default
    ``"ollama"``).  Constructor parameters override config values when
    supplied (useful for testing).
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        provider: str | None = None,
        endpoint: str | None = None,
        timeout: float | None = None,
    ) -> None:
        cfg_provider, cfg_model, cfg_endpoint, cfg_timeout = _resolve_config()
        self._provider = (provider or cfg_provider).strip().lower()
        self._model_name = model_name or cfg_model
        self._endpoint = (endpoint or cfg_endpoint).rstrip("/")
        self._timeout = timeout if timeout is not None else cfg_timeout
        # Lazy-loaded HF model (sentence-transformers only)
        self._model = None

    # ── sentence-transformers backend ────────────────────────

    def _load_st_model(self):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self._model_name)

    def _embed_sentence_transformers(self, texts: list[str]) -> NDArray[np.float32]:
        if self._model is None:
            self._load_st_model()
        vecs = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)

    # ── Ollama backend ───────────────────────────────────────

    # Maximum number of texts per Ollama /api/embed request.  Sending
    # large domains (200+ chunks) as a single request exceeds Ollama's
    # internal body-size limit and returns HTTP 400.
    _OLLAMA_BATCH_SIZE: int = 32

    def _embed_ollama(self, texts: list[str]) -> NDArray[np.float32]:
        import httpx

        url = f"{self._endpoint}/api/embed"
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._OLLAMA_BATCH_SIZE):
            batch = texts[i : i + self._OLLAMA_BATCH_SIZE]
            payload = {"model": self._model_name, "input": batch}
            resp = httpx.post(url, json=payload, timeout=self._timeout)
            if not resp.is_success:
                raise httpx.HTTPStatusError(
                    f"Ollama /api/embed returned {resp.status_code}: {resp.text}",
                    request=resp.request,
                    response=resp,
                )
            data = resp.json()
            embeddings = data.get("embeddings")
            if embeddings is None:
                raise RuntimeError(
                    f"Ollama /api/embed response missing 'embeddings' key; got keys: {list(data.keys())}"
                )
            all_embeddings.extend(embeddings)
        return np.asarray(all_embeddings, dtype=np.float32)

    # ── Public API ───────────────────────────────────────────

    def embed_texts(self, texts: list[str]) -> NDArray[np.float32]:
        """Return a ``(N, 384)`` float32 array of embeddings."""
        if self._provider == PROVIDER_OLLAMA:
            return self._embed_ollama(texts)
        return self._embed_sentence_transformers(texts)

    def embed_chunks(self, chunks: list[DocChunk]) -> NDArray[np.float32]:
        """Embed a list of chunks, returning their vector representations."""
        texts = [f"{c.heading}\n{c.text}" for c in chunks]
        return self.embed_texts(texts)

    def embed_query(self, query: str) -> NDArray[np.float32]:
        """Embed a single search query, returning a ``(384,)`` vector."""
        return self.embed_texts([query])[0]
