# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Graph backend abstraction + in-memory backend (R2.5, R2.9, R3.6, R10.2).

Mirrors ``src/admin_ops/changefeed/store.py``: an ABC, an in-memory backend for
tests/dev, and the ``set_backend_for_testing`` / ``_get_backend`` seam guarded by
an ``RLock``. The production ``NeptuneBackend`` is wired in a later AWS phase
(Phase 10); the ``ADMIN_DEV_BYPASS`` / Neptune selection branch here is a stub
that raises ``NotImplementedError`` so no AWS import is needed now. By default
``_get_backend()`` returns a module-level :class:`InMemoryGraphBackend` so tests
and the no-AWS dev path work, while keeping the ``set_backend_for_testing`` seam
identical to the change feed.

``GraphResult`` is imported from :mod:`result` (a tiny standalone module) rather
than defined here, so ``query.py`` can reuse the same model in Phase 5 without a
circular import between ``store`` and ``query``.

Idempotence (P-KG1) and referential safety (P-KG2): ``upsert`` merges nodes by
``node_id`` (last write updates props) and adds edges idempotently into a set
keyed by ``(source_id, edge_type, target_id)``. Because the pure mapper already
guarantees every edge endpoint is present in ``mutation.nodes`` (P-KG2), and
``upsert`` applies all nodes before edges, the stored graph stays referentially
safe.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timedelta
from threading import RLock

from src.admin_ops.kg.ingest import GraphMutation
from src.admin_ops.kg.model import GraphEdge, GraphNode
from src.admin_ops.kg.result import GraphResult

# Retention boundary: ChangeEvent graph data is retained >= 365 days (R10.2).
_RETENTION_DAYS = 365


class GraphUnreachable(RuntimeError):
    """Raised when the graph backend is unreachable. Routes -> HTTP 503 (R10.5)."""


def _contributing_ts(node: GraphNode) -> datetime | None:
    """Return the ``contributing_ts`` of a ChangeEvent node as a datetime.

    Non-ChangeEvent nodes (and ChangeEvent nodes lacking the prop) return None.
    """
    if node.type != "ChangeEvent":
        return None
    raw = node.props.get("contributing_ts")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:  # pragma: no cover - defensive guard
        return None


class GraphBackend(ABC):
    """Swappable graph store. Mirrors the change-feed backend ABC."""

    @abstractmethod
    def upsert(self, mutation: GraphMutation) -> None:
        """Idempotently merge the mutation's nodes and edges (P-KG1, P-KG2)."""

    @abstractmethod
    def get_node(self, node_id: str) -> GraphNode | None:
        """Return the node with ``node_id`` or None."""

    @abstractmethod
    def neighbors(self, node_id: str, hops: int, since: datetime) -> GraphResult:
        """Return nodes/edges reachable from ``node_id`` within ``hops``,
        windowed by contributing timestamp (R5.1)."""

    @abstractmethod
    def all_change_events(self, since: datetime) -> list[GraphNode]:
        """Return ChangeEvent nodes with ``contributing_ts >= since``."""

    @abstractmethod
    def health(self) -> dict:
        """Return a small health/status dict."""


class InMemoryGraphBackend(GraphBackend):
    """Dict-of-nodes + adjacency set backend for tests and the dev demo.

    * ``_nodes``: ``dict[node_id, GraphNode]`` — merged by ``node_id``.
    * ``_edges``: ``set[(source_id, edge_type, target_id)]`` — idempotent.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: set[tuple[str, str, str]] = set()

    # --- mutation -----------------------------------------------------------

    def upsert(self, mutation: GraphMutation) -> None:
        # Nodes first so edges can never reference a missing node (P-KG2).
        for node in mutation.nodes:
            existing = self._nodes.get(node.node_id)
            if existing is None:
                self._nodes[node.node_id] = node
            else:
                # Last-write updates props; merge so re-ingesting the same
                # event is a no-op on graph state (P-KG1).
                merged_props = {**existing.props, **node.props}
                self._nodes[node.node_id] = GraphNode(
                    node_id=node.node_id,
                    type=node.type,
                    label=node.label,
                    props=merged_props,
                )
        for edge in mutation.edges:
            self._edges.add((edge.source_id, edge.edge_type, edge.target_id))

    # --- reads --------------------------------------------------------------

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def _edges_as_models(self, keys: set[tuple[str, str, str]]) -> list[GraphEdge]:
        return [
            GraphEdge(edge_type=etype, source_id=src, target_id=tgt)
            for (src, etype, tgt) in keys
        ]

    def neighbors(self, node_id: str, hops: int, since: datetime) -> GraphResult:
        """Bounded BFS up to ``hops`` (1-3) from ``node_id``.

        Reachable nodes and the edges traversed are returned. A ChangeEvent
        node is only included when its ``contributing_ts >= since``; a
        non-ChangeEvent node is included when reached via an in-window path
        (i.e. it is traversed during BFS). Deterministic: frontier expansion
        sorts node_ids and edges sort by their key tuple.
        """
        focus = self._nodes.get(node_id)
        result_nodes: dict[str, GraphNode] = {}
        result_edges: set[tuple[str, str, str]] = set()
        if focus is None:
            return GraphResult(nodes=[], edges=[], focus=node_id, window={})

        # The focus is always included if in-window (ChangeEvent) or any node.
        def in_window(n: GraphNode) -> bool:
            cts = _contributing_ts(n)
            return cts is None or cts >= since

        visited: set[str] = set()
        # Each frontier item: (node_id, depth). BFS bounded by hops.
        frontier: deque[tuple[str, int]] = deque([(node_id, 0)])
        visited.add(node_id)
        if in_window(focus):
            result_nodes[node_id] = focus

        while frontier:
            current_id, depth = frontier.popleft()
            if depth >= hops:
                continue
            # Deterministic adjacency: edges touching current_id, sorted.
            adjacency = sorted(
                e for e in self._edges if e[0] == current_id or e[2] == current_id
            )
            for src, etype, tgt in adjacency:
                other = tgt if src == current_id else src
                other_node = self._nodes.get(other)
                if other_node is None:
                    continue
                if not in_window(other_node):
                    continue
                result_edges.add((src, etype, tgt))
                if other not in result_nodes:
                    result_nodes[other] = other_node
                if other not in visited:
                    visited.add(other)
                    frontier.append((other, depth + 1))

        window = {"from": since.isoformat()}
        ordered_nodes = [result_nodes[k] for k in sorted(result_nodes)]
        ordered_edges = self._edges_as_models(result_edges)
        ordered_edges.sort(key=lambda e: (e.source_id, e.edge_type, e.target_id))
        return GraphResult(
            nodes=ordered_nodes, edges=ordered_edges, focus=node_id, window=window
        )

    def all_change_events(self, since: datetime) -> list[GraphNode]:
        """Return ChangeEvent nodes with ``contributing_ts >= since``."""
        out: list[GraphNode] = []
        for node in self._nodes.values():
            if node.type != "ChangeEvent":
                continue
            cts = _contributing_ts(node)
            if cts is not None and cts >= since:
                out.append(node)
        out.sort(key=lambda n: n.node_id)
        return out

    def iter_nodes(self) -> list[GraphNode]:
        """Return all stored nodes (read-only snapshot).

        Public read accessor used by the specialized walk queries in
        :mod:`query` so they need not reach into ``_nodes`` directly. The list
        is a fresh copy; mutating it does not affect the backend.
        """
        return list(self._nodes.values())

    def iter_edges(self) -> list[GraphEdge]:
        """Return all stored edges as :class:`GraphEdge` models (read-only).

        Public read accessor mirroring :meth:`iter_nodes` for the walk queries
        in :mod:`query`. Built from the internal edge-key set, so it is a fresh
        copy that does not alias backend state.
        """
        return self._edges_as_models(self._edges)

    def health(self) -> dict:
        return {
            "status": "ok",
            "backend": "in_memory",
            "nodes": len(self._nodes),
            "edges": len(self._edges),
        }

    # --- retention ----------------------------------------------------------

    def prune(self, older_than: datetime) -> int:
        """Remove ChangeEvent nodes whose ``contributing_ts < older_than`` and
        any edges referencing them (R10.2). Returns the number of nodes pruned.

        The 365-day boundary is the caller's responsibility; pass
        ``datetime.now(tz) - timedelta(days=365)``. See :func:`retention_cutoff`.
        """
        to_remove: set[str] = set()
        for node in list(self._nodes.values()):
            if node.type != "ChangeEvent":
                continue
            cts = _contributing_ts(node)
            if cts is not None and cts < older_than:
                to_remove.add(node.node_id)
        if not to_remove:
            return 0
        for node_id in to_remove:
            self._nodes.pop(node_id, None)
        self._edges = {
            e for e in self._edges if e[0] not in to_remove and e[2] not in to_remove
        }
        return len(to_remove)


def retention_cutoff(now: datetime) -> datetime:
    """Return the 365-day retention cutoff relative to ``now`` (R10.2)."""
    return now - timedelta(days=_RETENTION_DAYS)


# ─── Production Neptune backend (R4.1, R4.8, R5.2, R10.5; AWS) ────────────────
#
# openCypher over the Neptune HTTPS endpoint. boto3 / requests are imported
# lazily inside the methods so importing this module never requires AWS. All
# caller-supplied values reach Neptune ONLY as bound parameters; the single
# non-parameterizable value — the variable-length pattern's upper bound — is the
# validated integer ``hops ∈ {1,2,3}`` selecting one of three pre-written,
# reviewed query strings (P-KG6, R5.2; enforced by
# tests/admin_ops/kg/test_query_parameterization.py).

# Node/edge upsert. MERGE is upsert-by-pattern; MERGE on both endpoints first
# guarantees referential integrity (P-KG2). Every value is a bound parameter.
_UPSERT_NODE_CYPHER = (
    "MERGE (n {node_id: $node_id}) "
    "SET n.type = $type, n.label = $label, n += $props"
)
_UPSERT_EDGE_CYPHER = (
    "MERGE (s {node_id: $source_id}) "
    "MERGE (t {node_id: $target_id}) "
    "MERGE (s)-[r:RELATES {edge_type: $edge_type}]->(t)"
)

# Bounded traversal. Neptune openCypher does not bind the upper bound of a
# variable-length pattern, so we keep three pre-written strings keyed by the
# validated integer hops; node_id and since remain bound parameters. There is
# no f-string / % interpolation of any caller value here.
_NEIGHBORS_CYPHER_BY_HOPS: dict[int, str] = {
    1: (
        "MATCH (focus {node_id: $focus}) "
        "MATCH path = (focus)-[*1..1]-(n) "
        "WHERE n.contributing_ts IS NULL OR n.contributing_ts >= $since "
        "RETURN path"
    ),
    2: (
        "MATCH (focus {node_id: $focus}) "
        "MATCH path = (focus)-[*1..2]-(n) "
        "WHERE n.contributing_ts IS NULL OR n.contributing_ts >= $since "
        "RETURN path"
    ),
    3: (
        "MATCH (focus {node_id: $focus}) "
        "MATCH path = (focus)-[*1..3]-(n) "
        "WHERE n.contributing_ts IS NULL OR n.contributing_ts >= $since "
        "RETURN path"
    ),
}


def neighbors_cypher_for_hops(hops: int) -> str:
    """Return the pre-written neighbors query string for ``hops ∈ {1,2,3}``.

    Raises ``ValueError`` for any other value so an out-of-range hop can never
    be interpolated into a query string (R5.2, P-KG6). Exposed at module scope
    so the parameterization test can assert the selection is by lookup, not by
    interpolation of a caller value.
    """
    try:
        return _NEIGHBORS_CYPHER_BY_HOPS[hops]
    except KeyError as exc:
        raise ValueError(f"hops must be one of {{1,2,3}}, got {hops!r}") from exc


class NeptuneBackend(GraphBackend):  # pragma: no cover - exercised only in AWS
    """openCypher graph backend over a Neptune HTTPS endpoint.

    boto3 / requests are imported lazily so importing this module never needs
    AWS. The endpoint is read at runtime from ``config.yaml`` via
    ``require_config`` — no resource id is embedded in source (R4.8). A
    connectivity failure raises :class:`GraphUnreachable` so routes return a
    structured 503 with no stale data (R10.5).
    """

    def __init__(self, endpoint: str | None = None) -> None:
        if endpoint is None:
            from src.admin_ops.config.require import require_config

            endpoint = require_config("knowledge_graph", "neptune_endpoint")
        self._endpoint = endpoint

    # --- transport ----------------------------------------------------------

    def _execute(self, query: str, params: dict) -> dict:
        """POST one openCypher query with bound ``params`` to Neptune.

        All caller values travel in ``params`` (the openCypher ``parameters``
        body), never interpolated into ``query``. Any transport error becomes
        :class:`GraphUnreachable`.
        """
        import json as _json

        import requests  # lazy: no import at module load

        url = f"https://{self._endpoint}:8182/opencypher"
        try:
            resp = requests.post(
                url,
                data={"query": query, "parameters": _json.dumps(params)},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - any failure -> unreachable
            raise GraphUnreachable(str(exc)) from exc

    # --- mutation -----------------------------------------------------------

    def upsert(self, mutation: GraphMutation) -> None:
        # Nodes first (referential safety, P-KG2), then edges. Each value is a
        # bound parameter; MERGE makes re-ingest a no-op (P-KG1).
        for node in mutation.nodes:
            self._execute(
                _UPSERT_NODE_CYPHER,
                {
                    "node_id": node.node_id,
                    "type": node.type,
                    "label": node.label,
                    "props": dict(node.props),
                },
            )
        for edge in mutation.edges:
            self._execute(
                _UPSERT_EDGE_CYPHER,
                {
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                    "edge_type": edge.edge_type,
                },
            )

    # --- reads --------------------------------------------------------------

    def get_node(self, node_id: str) -> GraphNode | None:
        data = self._execute(
            "MATCH (n {node_id: $node_id}) RETURN n LIMIT 1",
            {"node_id": node_id},
        )
        return _node_from_neptune_result(data)

    def neighbors(self, node_id: str, hops: int, since: datetime) -> GraphResult:
        # hops selects a pre-written string (never interpolated); node_id and
        # since are bound parameters.
        query = neighbors_cypher_for_hops(hops)
        data = self._execute(
            query, {"focus": node_id, "since": since.isoformat()}
        )
        return _graph_result_from_neptune_paths(data, focus=node_id, since=since)

    def all_change_events(self, since: datetime) -> list[GraphNode]:
        data = self._execute(
            "MATCH (n {type: 'ChangeEvent'}) "
            "WHERE n.contributing_ts >= $since RETURN n",
            {"since": since.isoformat()},
        )
        return _nodes_from_neptune_rows(data)

    def health(self) -> dict:
        try:
            self._execute("MATCH (n) RETURN count(n) AS c LIMIT 1", {})
            return {"status": "ok", "backend": "neptune"}
        except GraphUnreachable as exc:
            return {"status": "unreachable", "backend": "neptune", "error": str(exc)}


def _node_from_neptune_result(data: dict) -> GraphNode | None:
    """Build a single GraphNode from a Neptune openCypher result, or None."""
    rows = data.get("results", []) if isinstance(data, dict) else []
    if not rows:
        return None
    raw = rows[0].get("n", {})
    return _node_from_neptune_props(raw)


def _nodes_from_neptune_rows(data: dict) -> list[GraphNode]:
    rows = data.get("results", []) if isinstance(data, dict) else []
    out: list[GraphNode] = []
    for row in rows:
        node = _node_from_neptune_props(row.get("n", {}))
        if node is not None:
            out.append(node)
    return out


def _node_from_neptune_props(raw: dict) -> GraphNode | None:
    """Map a Neptune node payload onto a GraphNode (props minus reserved keys)."""
    props = raw.get("~properties", raw) if isinstance(raw, dict) else {}
    node_id = props.get("node_id")
    ntype = props.get("type")
    if not node_id or not ntype:
        return None
    label = props.get("label", "")
    reserved = {"node_id", "type", "label"}
    extra = {k: v for k, v in props.items() if k not in reserved}
    return GraphNode(node_id=node_id, type=ntype, label=label, props=extra)


def _graph_result_from_neptune_paths(
    data: dict, focus: str, since: datetime
) -> GraphResult:
    """Flatten Neptune path rows into a deterministic GraphResult.

    Path parsing depends on the Neptune response envelope; this is exercised
    only against a live endpoint (Phase 10 integration tests). The shape mirrors
    the in-memory backend's GraphResult so the query layer is backend-agnostic.
    """
    nodes: dict[str, GraphNode] = {}
    edges: set[tuple[str, str, str]] = set()
    rows = data.get("results", []) if isinstance(data, dict) else []
    for row in rows:
        path = row.get("path") or row.get("p") or {}
        for seg in path.get("objects", []) if isinstance(path, dict) else []:
            node = _node_from_neptune_props(seg) if isinstance(seg, dict) else None
            if node is not None:
                nodes[node.node_id] = node
    ordered_nodes = [nodes[k] for k in sorted(nodes)]
    ordered_edges = [
        GraphEdge(edge_type=t, source_id=s, target_id=g)
        for (s, t, g) in sorted(edges)
    ]
    return GraphResult(
        nodes=ordered_nodes,
        edges=ordered_edges,
        focus=focus,
        window={"from": since.isoformat()},
    )


# ─── Module state (mirrors changefeed/store.py) ──────────────────────────────


_backend: GraphBackend | None = None
_lock = RLock()


def _get_backend() -> GraphBackend:
    global _backend
    with _lock:
        if _backend is None:
            # Local-dev / demo escape: when ADMIN_DEV_BYPASS=1 (set in
            # ui/.env.local for demos), build a JSON-seeded
            # InMemoryGraphBackend from the existing dev change-feed JSON +
            # seeded tickets, so the whole feature runs in-process with no
            # AWS — identical pattern to changefeed.store._get_backend.
            if os.environ.get("ADMIN_DEV_BYPASS") == "1":
                from src.admin_ops.kg._dev_store import build_seeded_backend

                _backend = build_seeded_backend()
            else:
                # Production path: use NeptuneBackend when an endpoint is
                # configured (config.yaml::knowledge_graph.neptune_endpoint).
                # If the endpoint is absent/empty (e.g. local non-dev runs,
                # tests that did not call set_backend_for_testing), fall back
                # to an in-memory backend so importing/using the module never
                # requires AWS. boto3/requests are imported lazily inside
                # NeptuneBackend, so this branch stays import-safe.
                from src.admin_ops.config.require import optional_config

                endpoint = optional_config("knowledge_graph", "neptune_endpoint")
                if endpoint:
                    _backend = NeptuneBackend(endpoint=endpoint)
                else:
                    _backend = InMemoryGraphBackend()
        return _backend


def set_backend_for_testing(backend: GraphBackend | None) -> None:
    global _backend
    with _lock:
        _backend = backend
