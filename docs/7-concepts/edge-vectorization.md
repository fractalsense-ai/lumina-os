---
version: 1.1.0
last_updated: 2026-06-15
---

# Edge Vectorization — Per-Domain Vector Stores

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-06-15  

---

The retrieval subsystem embeds domain documentation, physics declarations, glossary entries,
and other textual artefacts into vector stores for semantic search.  Early Lumina builds
used a single monolithic vector store — every domain's content lived in one `.npz` file.
This created three problems:

1. **Rebuild cost** — changing one domain's physics file required re-embedding every domain.
2. **Contamination** — search hits could leak cross-domain content into a session's context
   window, violating the self-containment contract in spirit even though not in code.
3. **Scaling** — adding a new domain pack increased rebuild time for all existing packs.

Edge Vectorization solves these by isolating each domain's vectors into its own
subdirectory and `.npz` file, managed by a registry that creates stores on demand.

### Embedding model

All vector embeddings use the **MiniLM** family of sentence-transformer models,
producing 384-dimensional vectors. Two providers are supported:

| Provider | Model name | Install | Env value |
|----------|-----------|---------|-----------|
| **Ollama** (default) | `all-minilm` | `ollama pull all-minilm` | `LUMINA_EMBEDDING_PROVIDER=ollama` |
| **HuggingFace** (fallback) | `all-MiniLM-L6-v2` | `pip install -e ".[retrieval]"` | `LUMINA_EMBEDDING_PROVIDER=huggingface` |

The Ollama provider is preferred for development because it shares the same Ollama instance
used for the SLM. The HuggingFace provider loads models locally via `sentence-transformers`
and requires no external service.

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `LUMINA_EMBEDDING_PROVIDER` | `ollama` | `ollama` or `huggingface` |
| `LUMINA_EMBEDDING_MODEL` | provider-dependent | Overrides the model name (`all-minilm` for Ollama, `all-MiniLM-L6-v2` for HuggingFace) |
| `LUMINA_EMBEDDING_ENDPOINT` | `http://localhost:11434` | Ollama base URL (ignored for HuggingFace) |

When neither provider is available (Ollama not running and `sentence-transformers` not
installed), the embedding layer degrades gracefully — vector stores remain empty and
vector-based routing (Pass 1.5) is silently skipped.

**CORS note:** The Ollama provider issues HTTP requests from the backend server process
(`src/lumina/retrieval/embedder.py`), not from the browser. Front-end clients never call
the embedding endpoint directly. If you configure Ollama with a custom CORS policy, ensure
`http://localhost:5173` (the Vite dev server) is permitted for API calls that proxy through
the backend.

---

## A. Per-Domain Vector Isolation

Each domain pack's embedded content is stored under a dedicated directory:

```
data/retrieval-index/
├── _global/
│   └── vectors.npz         ← root-level docs/specs/standards (routing index)
├── education/
│   └── vectors.npz         ← education domain pack content
├── agriculture/
│   └── vectors.npz         ← agriculture domain pack content
└── system/
    └── vectors.npz         ← system domain pack content
```

The `_global` store is special: it aggregates lightweight routing vectors from all domains
(high-level descriptions only, not full content).  It is used by the NLP semantic router
for vector-based domain classification — see §F.

### Isolation guarantee

A domain store contains embeddings derived **only** from that domain pack's files:
`domain-physics.yaml`, glossary entries, `domain-lib/` specifications, tool adapter
descriptions, and domain-scoped documentation under `domain-packs/<domain>/docs/`.  No
cross-domain content enters a domain store.

This means a per-domain search never returns content from another domain — structurally
enforced by the storage layout, not by post-hoc filtering.

---

## B. VectorStoreRegistry

The `VectorStoreRegistry` class manages per-domain `VectorStore` instances, creating them
lazily on first access.

```python
class VectorStoreRegistry:
    GLOBAL_DOMAIN = "_global"

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._stores: dict[str, VectorStore] = {}

    def get(self, domain_id: str) -> VectorStore:
        """Return (or create) the store for *domain_id*."""

    @property
    def global_store(self) -> VectorStore:
        """Shortcut for the lightweight routing store."""

    def domain_ids(self) -> list[str]:
        """List domain-ids that have a persisted store on disk."""

    def load_all(self) -> None:
        """Load every persisted domain store into memory."""
```

| Method | Returns | Notes |
|--------|---------|-------|
| `get(domain_id)` | `VectorStore` | Creates subdirectory on first call |
| `global_store` | `VectorStore` | Alias for `get("_global")` |
| `domain_ids()` | `list[str]` | Scans disk for directories with `vectors.npz` |
| `load_all()` | `None` | Pre-warms all persisted stores into memory |

The registry is instantiated once and injected into the NLP layer, the housekeeper, and
the daemon via `set_vector_registry()`.

---

## C. Domain-Scoped Ingestion

The `DocEmbedder` produces `DocChunk` instances, each tagged with a `domain_id`:

```python
@dataclass(frozen=True)
class DocChunk:
    source_path: str
    heading: str
    text: str
    content_hash: str
    content_type: str = "doc"
    domain_id: str = ""
```

During ingestion, chunks are routed to the correct domain store by their `domain_id` field.
The housekeeper's `rebuild_domain_index()` clears and re-embeds all content for a single
domain pack:

```python
rebuild_domain_index(
    domain_id="agriculture",
    registry=vector_registry,
    embedder=doc_embedder,
)
```

This rebuilds **only** the agriculture store — other domains are untouched.

---

## D. Daemon-Driven Rebuilds

The resource monitor daemon dispatches vector rebuilds as batch tasks when the system
is idle.  Three rebuild granularities are available:

| Function | Scope | When used |
|----------|-------|-----------|
| `rebuild_domain_index(domain_id, ...)` | Single domain | After a physics file or domain doc changes |
| `rebuild_group_library_dependents(library_id, ...)` | All domains referencing a Group Library | After a Group Library file changes |
| `rebuild_all_domain_indexes(...)` | Every domain + global | Full re-index (daemon batch, schema migration) |
| `rebuild_global_index(...)` | `_global` store only | After root-level docs/specs/standards change |

The daemon's `task_priority` list includes `rebuild_domain_vectors` alongside other
batch tasks like `glossary_expansion` and `knowledge_graph_rebuild`.  The daemon walks
this list in round-robin order during idle periods — see
[`resource-monitor-daemon(7)`](resource-monitor-daemon.md) §F.

Cross-domain tasks (those affecting multiple domains) are dispatched via
`run_cross_domain_task_preemptible()`, which checks the daemon's `PreemptionToken` between
domain iterations so the rebuild can yield cooperatively if system load spikes.

---

## E. Global Routing Index

The `_global` store serves a specific purpose: enabling the NLP semantic router to perform
fast vector similarity against a lightweight routing index **before** committing to a domain.

Content in the global store:

- One embedding per domain pack (derived from the domain's description and top-level
  keywords)
- Root-level specifications (`specs/`), standards (`standards/`), and system documentation
  (`docs/`) that are not domain-scoped

The global store is intentionally small — it contains routing hints, not full domain
content.  Once a domain is selected, per-domain search uses the domain's own isolated store.

---

## F. NLP Vector Routing — Pass 1.5

The NLP semantic router's `classify_domain()` runs three passes in sequence.  Edge
Vectorization adds **Pass 1.5** between the existing keyword pass and the spaCy vector
similarity pass:

| Pass | Method | Requirement |
|------|--------|-------------|
| 1 | Keyword matching | Always available |
| **1.5** | **Vector routing via global store** | `VectorStoreRegistry` injected and global store non-empty |
| 2 | spaCy vector similarity | spaCy with vector model loaded |

### How Pass 1.5 works

1. The incoming message is embedded via `DocEmbedder.embed_query(text)`.
2. The global store is searched for the top-5 nearest neighbours.
3. Hits are tallied by `domain_id` — each hit's cosine similarity score votes for its
   domain.
4. The domain with the highest total vote is selected if its average score meets the
   confidence threshold (`0.6`).
5. If no domain passes the threshold, classification falls through to Pass 2 (spaCy).

```python
# Simplified from src/lumina/core/nlp.py — Pass 1.5
q_vec = _doc_embedder.embed_query(text)
hits = _vector_registry.global_store.search(q_vec, k=5)
vec_votes: dict[str, float] = {}
for h in hits:
    did = h.chunk.domain_id
    if did and did in candidates:
        vec_votes[did] = vec_votes.get(did, 0.0) + h.score
if vec_votes:
    best_id = max(vec_votes, key=vec_votes.__getitem__)
    avg_score = vec_votes[best_id] / hit_count
    if avg_score >= _CONFIDENCE_THRESHOLD:
        return {"domain_id": best_id, "confidence": avg_score, "method": "vector"}
```

Pass 1.5 is a **soft dependency** — when the vector registry is not configured (no embedder
available, no persisted stores), the pass is silently skipped with no degradation.  This
mirrors the spaCy soft dependency model: the system degrades gracefully through the pass
chain.

### Why Pass 1.5 before spaCy?

The global store's embeddings are domain-tuned (built from actual domain content), whereas
spaCy's vectors are general-purpose.  Domain-tuned vectors produce more accurate
classification for specialised vocabulary.  spaCy remains as a final similarity fallback
when the global store is empty or the result is inconclusive.

---

## SEE ALSO

- [`nlp-semantic-router(7)`](nlp-semantic-router.md) — two-tier NLP architecture and full classification pipeline
- [`group-libraries-and-tools(7)`](group-libraries-and-tools.md) — Group Library dependency-aware rebuilds
- [`execution-route-compilation(7)`](execution-route-compilation.md) — route compiler uses library indexes built from the same discovery pass
- [`resource-monitor-daemon(7)`](resource-monitor-daemon.md) — daemon-driven idle dispatch and preemption protocol
- `src/lumina/retrieval/vector_store.py` — `VectorStore`, `VectorStoreRegistry`
- `src/lumina/retrieval/housekeeper.py` — `rebuild_domain_index()`, `rebuild_group_library_dependents()`, `rebuild_all_domain_indexes()`, `rebuild_global_index()`
- `src/lumina/retrieval/embedder.py` — `DocChunk`, `DocEmbedder`
- `src/lumina/core/nlp.py` — `classify_domain()` Pass 1.5 implementation, `set_vector_registry()`
