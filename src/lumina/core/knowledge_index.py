"""knowledge_index.py — Global Knowledge Index for Project Lumina.

Centralises three layers of pre-processed knowledge that the system
relies on *before* any SLM or LLM is invoked:

1. **Glossary routing table** — every glossary term + alias → domain_id.
   Used by :func:`lumina.core.nlp.classify_domain` as Pass 0 (O(1) lookup).
2. **Concept graph** — nodes for glossary terms, invariants, standing orders,
   artifacts; edges for related_terms, prerequisite chains, governs links.
3. **Vector embeddings** — delegated to the existing MiniLM housekeeper /
   :class:`lumina.retrieval.vector_store.VectorStore`.

The index is persisted as flat JSON at ``data/knowledge-index/`` and
eagerly loaded at server startup.  The ``knowledge_graph_rebuild``
daemon batch task calls :meth:`KnowledgeIndex.build` to refresh it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

log = logging.getLogger("lumina.knowledge-index")


# ── Data structures ──────────────────────────────────────────

@dataclass
class ConceptNode:
    """A single concept in the knowledge graph."""

    node_id: str
    label: str
    kind: str  # "glossary_term" | "invariant" | "standing_order" | "artifact" | "module"
    domain_id: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConceptNode:
        return cls(
            node_id=d["node_id"],
            label=d["label"],
            kind=d["kind"],
            domain_id=d["domain_id"],
            detail=d.get("detail", {}),
        )


@dataclass
class ConceptEdge:
    """A directed edge in the concept graph."""

    source: str  # node_id
    target: str  # node_id
    relation: str  # "related_term" | "prerequisite" | "governs" | "belongs_to"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConceptEdge:
        return cls(source=d["source"], target=d["target"], relation=d["relation"])


# ── Knowledge Index ──────────────────────────────────────────

class KnowledgeIndex:
    """Global knowledge index with glossary routing, concept graph, and
    delegation to the vector-embedding layer.

    Thread-safe: all public methods acquire ``_lock``.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._glossary_table: dict[str, str] = {}  # lowered term → domain_id
        self._nodes: dict[str, ConceptNode] = {}  # node_id → ConceptNode
        self._edges: list[ConceptEdge] = []
        self._built_at: float | None = None
        # Adjacency list for fast traversal: node_id → list[ConceptEdge]
        self._adj: dict[str, list[ConceptEdge]] = {}

    # ── Build ─────────────────────────────────────────────────

    def build(self, domain_contexts: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """(Re-)build the index from all loaded domain contexts.

        Parameters
        ----------
        domain_contexts:
            ``{domain_id: runtime_context}`` — each runtime_context must
            contain a ``"domain"`` key with the domain-physics dict.

        Returns a summary dict with counts.
        """
        start = time.monotonic()

        glossary_table: dict[str, str] = {}
        nodes: dict[str, ConceptNode] = {}
        edges: list[ConceptEdge] = []

        for domain_id, ctx in domain_contexts.items():
            physics = ctx.get("domain") or {}
            self._index_glossary(domain_id, physics, glossary_table, nodes, edges)
            self._index_modules(domain_id, physics, nodes, edges)
            self._index_invariants(domain_id, physics, nodes, edges)
            self._index_standing_orders(domain_id, physics, nodes, edges)

        # Build adjacency list
        adj: dict[str, list[ConceptEdge]] = {}
        for edge in edges:
            adj.setdefault(edge.source, []).append(edge)

        with self._lock:
            self._glossary_table = glossary_table
            self._nodes = nodes
            self._edges = edges
            self._adj = adj
            self._built_at = time.time()

        elapsed = time.monotonic() - start
        summary = {
            "glossary_terms": len(glossary_table),
            "concept_nodes": len(nodes),
            "concept_count": len(nodes),
            "concept_edges": len(edges),
            "domains_indexed": len(domain_contexts),
            "elapsed_seconds": round(elapsed, 4),
        }
        log.info("KnowledgeIndex built: %s", summary)
        return summary

    # ── Indexers (private, called during build) ───────────────

    @staticmethod
    def _index_glossary(
        domain_id: str,
        physics: dict[str, Any],
        glossary_table: dict[str, str],
        nodes: dict[str, ConceptNode],
        edges: list[ConceptEdge],
    ) -> None:
        glossary = physics.get("glossary") or []
        for entry in glossary:
            term = str(entry.get("term", "")).strip()
            if not term:
                continue

            node_id = f"glossary:{domain_id}:{term.lower()}"
            nodes[node_id] = ConceptNode(
                node_id=node_id,
                label=term,
                kind="glossary_term",
                domain_id=domain_id,
                detail={
                    "definition": entry.get("definition", ""),
                    "aliases": entry.get("aliases") or [],
                },
            )

            # Register the term and all aliases in the routing table
            glossary_table[term.lower()] = domain_id
            for alias in entry.get("aliases") or []:
                alias_lower = str(alias).lower().strip()
                if alias_lower:
                    glossary_table[alias_lower] = domain_id

            # related_terms edges
            for related in entry.get("related_terms") or []:
                related_lower = str(related).lower().strip()
                target_id = f"glossary:{domain_id}:{related_lower}"
                edges.append(ConceptEdge(
                    source=node_id,
                    target=target_id,
                    relation="related_term",
                ))

    @staticmethod
    def _index_modules(
        domain_id: str,
        physics: dict[str, Any],
        nodes: dict[str, ConceptNode],
        edges: list[ConceptEdge],
    ) -> None:
        modules = physics.get("modules") or []
        for mod in modules:
            mod_id = mod.get("module_id", "")
            if not mod_id:
                continue

            node_id = f"module:{domain_id}:{mod_id}"
            nodes[node_id] = ConceptNode(
                node_id=node_id,
                label=mod_id,
                kind="module",
                domain_id=domain_id,
                detail={"description": mod.get("description", "")},
            )

            # Prerequisite edges
            for prereq in mod.get("prerequisites") or []:
                target_id = f"module:{domain_id}:{prereq}"
                edges.append(ConceptEdge(
                    source=node_id,
                    target=target_id,
                    relation="prerequisite",
                ))

            # Artifact nodes + belongs_to edges
            for artifact in mod.get("artifacts") or []:
                art_name = artifact.get("name", "")
                if not art_name:
                    continue
                art_id = f"artifact:{domain_id}:{art_name.lower()}"
                nodes[art_id] = ConceptNode(
                    node_id=art_id,
                    label=art_name,
                    kind="artifact",
                    domain_id=domain_id,
                    detail={k: v for k, v in artifact.items() if k != "name"},
                )
                edges.append(ConceptEdge(
                    source=art_id, target=node_id, relation="belongs_to",
                ))

    @staticmethod
    def _index_invariants(
        domain_id: str,
        physics: dict[str, Any],
        nodes: dict[str, ConceptNode],
        edges: list[ConceptEdge],
    ) -> None:
        invariants = physics.get("invariants") or []
        for inv in invariants:
            inv_id_raw = inv.get("id", "")
            if not inv_id_raw:
                continue
            node_id = f"invariant:{domain_id}:{inv_id_raw}"
            nodes[node_id] = ConceptNode(
                node_id=node_id,
                label=inv_id_raw,
                kind="invariant",
                domain_id=domain_id,
                detail={
                    "description": inv.get("description", ""),
                    "severity": inv.get("severity", ""),
                },
            )
            # Link to the standing order triggered on violation
            so_ref = inv.get("standing_order_on_violation")
            if so_ref:
                target_id = f"standing_order:{domain_id}:{so_ref}"
                edges.append(ConceptEdge(
                    source=node_id, target=target_id, relation="governs",
                ))

    @staticmethod
    def _index_standing_orders(
        domain_id: str,
        physics: dict[str, Any],
        nodes: dict[str, ConceptNode],
        edges: list[ConceptEdge],
    ) -> None:
        standing_orders = physics.get("standing_orders") or []
        for so in standing_orders:
            so_id = so.get("id", "")
            if not so_id:
                continue
            node_id = f"standing_order:{domain_id}:{so_id}"
            nodes[node_id] = ConceptNode(
                node_id=node_id,
                label=so_id,
                kind="standing_order",
                domain_id=domain_id,
                detail={"description": so.get("description", "")},
            )

    # ── Query ─────────────────────────────────────────────────

    def lookup_term(self, term: str) -> str | None:
        """Return the domain_id that owns *term*, or None."""
        with self._lock:
            return self._glossary_table.get(term.lower().strip())

    def lookup_terms(self, terms: list[str]) -> dict[str, str]:
        """Batch lookup: return ``{term: domain_id}`` for every match."""
        result: dict[str, str] = {}
        with self._lock:
            for t in terms:
                key = t.lower().strip()
                if key in self._glossary_table:
                    result[t] = self._glossary_table[key]
        return result

    def get_node(self, node_id: str) -> ConceptNode | None:
        with self._lock:
            return self._nodes.get(node_id)

    def get_related(self, node_id: str, depth: int = 1) -> list[ConceptNode]:
        """Return nodes reachable from *node_id* within *depth* hops."""
        with self._lock:
            visited: set[str] = set()
            frontier = {node_id}
            for _ in range(depth):
                next_frontier: set[str] = set()
                for nid in frontier:
                    for edge in self._adj.get(nid, []):
                        if edge.target not in visited and edge.target != node_id:
                            next_frontier.add(edge.target)
                visited |= next_frontier
                frontier = next_frontier
            return [self._nodes[nid] for nid in visited if nid in self._nodes]

    @property
    def glossary_table(self) -> dict[str, str]:
        """Read-only copy of the glossary routing table."""
        with self._lock:
            return dict(self._glossary_table)

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "glossary_terms": len(self._glossary_table),
                "concept_nodes": len(self._nodes),
                "concept_edges": len(self._edges),
                "built_at": self._built_at,
            }

    # ── Persistence ───────────────────────────────────────────

    def save(self, directory: Path) -> None:
        """Persist the index to *directory* as JSON files."""
        directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            (directory / "glossary_table.json").write_text(
                json.dumps(self._glossary_table, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (directory / "concept_graph.json").write_text(
                json.dumps(
                    {
                        "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
                        "edges": [e.to_dict() for e in self._edges],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        log.info(
            "KnowledgeIndex saved to %s (%d terms, %d nodes, %d edges)",
            directory, len(self._glossary_table), len(self._nodes), len(self._edges),
        )

    def load(self, directory: Path) -> bool:
        """Load a previously saved index.  Returns True if loaded successfully."""
        gt_path = directory / "glossary_table.json"
        cg_path = directory / "concept_graph.json"
        if not gt_path.exists() or not cg_path.exists():
            log.info("KnowledgeIndex: no persisted data at %s", directory)
            return False

        glossary_table = json.loads(gt_path.read_text(encoding="utf-8"))
        cg = json.loads(cg_path.read_text(encoding="utf-8"))
        nodes = {nid: ConceptNode.from_dict(d) for nid, d in cg.get("nodes", {}).items()}
        edges = [ConceptEdge.from_dict(d) for d in cg.get("edges", [])]
        adj: dict[str, list[ConceptEdge]] = {}
        for edge in edges:
            adj.setdefault(edge.source, []).append(edge)

        with self._lock:
            self._glossary_table = glossary_table
            self._nodes = nodes
            self._edges = edges
            self._adj = adj
            self._built_at = time.time()

        log.info(
            "KnowledgeIndex loaded from %s (%d terms, %d nodes, %d edges)",
            directory, len(glossary_table), len(nodes), len(edges),
        )
        return True
