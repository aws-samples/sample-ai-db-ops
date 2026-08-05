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

"""Read-only graph traversal and analysis queries (R5.1-R5.5, R5.7, R7.4, R8.3).

All functions here are READ-ONLY against ``store._get_backend()`` (P-KG5): they
never upsert, never invoke an agent, and never write to any tracked store. They
return the shared :class:`GraphResult` (from :mod:`result`) or, for the
unticketed detector, an :class:`UnticketedResult`.

Query surface (design Component 5):

* :func:`connected` — bounded traversal from a focus node, validating all three
  preconditions JOINTLY (hops in 1..3 AND days in 1..365 AND focus exists),
  raising :class:`InvalidQuery` naming the offending parameter (S3, R5.2, R5.3).
* :func:`database_ddl_activity` — DDL ChangeEvents whose table BELONGS_TO a
  database, with their MODIFIED_BY principals and CAUSED_BY tickets (R5.5).
* :func:`ticket_changes` — every ChangeEvent CAUSED_BY a ticket (R8.3).
* :func:`principal_changes` — every ChangeEvent MODIFIED_BY a principal (R8.3).
* :func:`unticketed_changes` — high/critical DDL ChangeEvents with no CAUSED_BY
  edge to any Ticket, within the window (R7.4, P-KG7).

Window filtering uses the ChangeEvent ``contributing_ts`` prop (an ISO string),
matching the backend's existing ``_contributing_ts`` helper. The window is
``[now_utc - days, now_utc]``; each query records the exact ``since`` it used in
``GraphResult.window["from"]`` so callers (and tests) can reason about the
precise boundary without recomputing ``now``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field

from src.admin_ops.kg import store
from src.admin_ops.kg.model import GraphEdge, GraphNode
from src.admin_ops.kg.result import GraphResult
from src.admin_ops.kg.store import InMemoryGraphBackend

# Severities that make an unticketed DDL change noteworthy (R7.4, P-KG7).
_UNTICKETED_SEVERITIES: frozenset[str] = frozenset({"high", "critical"})


class InvalidQuery(ValueError):
    """A query parameter failed validation. The message names the bad param.

    Used by :func:`connected` for the joint precondition (S3, R5.3): the
    ``parameter`` attribute is one of ``"hops"``, ``"days"``, or
    ``"focus_node_id"``.
    """

    def __init__(self, parameter: str) -> None:
        self.parameter = parameter
        super().__init__(f"invalid query parameter: {parameter}")


class TraversalParams(BaseModel):
    """Validated parameters for :func:`connected` (R5.2, R5.3)."""

    model_config = ConfigDict(extra="forbid")

    focus_node_id: str = Field(min_length=1)
    hops: int = Field(ge=1, le=3)  # R5.2/R5.3
    days: int = Field(ge=1, le=365)  # R5.2/R5.3


class UnticketedResult(BaseModel):
    """Unticketed high/critical DDL ChangeEvents within a window (R7.4)."""

    model_config = ConfigDict(extra="forbid")

    events: list[GraphNode] = []
    complete: bool = True
    reason: str | None = None


# ─── internal helpers ────────────────────────────────────────────────────────


def _now() -> datetime:
    """Return the current UTC instant (single source of 'now' for windows)."""
    return datetime.now(timezone.utc)


def _contributing_ts(node: GraphNode) -> datetime | None:
    """Return a ChangeEvent node's ``contributing_ts`` as a datetime, or None.

    Mirrors ``store._contributing_ts``: non-ChangeEvent nodes (and ChangeEvent
    nodes lacking the prop) return None.
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


def _is_in_int_range(value: object, low: int, high: int) -> bool:
    """True iff ``value`` is a real int (not bool) within ``[low, high]``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return low <= value <= high


def _snapshot() -> tuple[list[GraphNode], list[GraphEdge]]:
    """Return (nodes, edges) from the active backend for walk queries.

    The in-memory backend is authoritative and exposes ``iter_nodes`` /
    ``iter_edges``. The Neptune walk path is a later AWS phase; until then a
    non-in-memory backend raises ``NotImplementedError`` rather than silently
    returning an empty graph.
    """
    backend = store._get_backend()
    if not isinstance(backend, InMemoryGraphBackend):  # pragma: no cover
        raise NotImplementedError(
            "walk queries require the in-memory backend (Neptune walk is a "
            "later phase)"
        )
    return backend.iter_nodes(), backend.iter_edges()


def _window(since: datetime, now: datetime) -> dict:
    """Build the ``GraphResult.window`` dict for a windowed query."""
    return {"from": since.isoformat(), "to": now.isoformat()}


# ─── public queries ──────────────────────────────────────────────────────────


def connected(params: TraversalParams) -> GraphResult:
    """Everything reachable from ``focus`` within ``hops`` and in-window (R5.1).

    Validates all three preconditions JOINTLY before any traversal (S3, R5.3):

    * ``hops`` is an int in ``1..3`` (else :class:`InvalidQuery` ``"hops"``),
    * ``days`` is an int in ``1..365`` (else :class:`InvalidQuery` ``"days"``),
    * ``focus_node_id`` exists in the backend (else ``"focus_node_id"``).

    Pydantic already enforces the ``hops``/``days`` ranges on a normally
    constructed :class:`TraversalParams`; the explicit checks here also defend
    against a caller that bypasses the model (e.g. ``model_construct``). On any
    failure no traversal is performed.
    """
    if not _is_in_int_range(params.hops, 1, 3):
        raise InvalidQuery("hops")
    if not _is_in_int_range(params.days, 1, 365):
        raise InvalidQuery("days")

    backend = store._get_backend()
    if backend.get_node(params.focus_node_id) is None:
        raise InvalidQuery("focus_node_id")

    since = _now() - timedelta(days=params.days)
    return backend.neighbors(params.focus_node_id, params.hops, since)


def database_ddl_activity(database_node_id: str, days: int) -> GraphResult:
    """DDL activity against a database within the window (R5.5).

    Returns the DDL ``ChangeEvent`` nodes whose ``RUNS_AGAINST`` table
    ``BELONGS_TO`` ``database_node_id``, plus the ``MODIFIED_BY`` principals and
    ``CAUSED_BY`` tickets, plus the tables and the database node — a materialized
    subgraph, not a flat list (R8). Only events with ``ddl_kind`` set and a
    ``contributing_ts`` within the window are included.
    """
    if not _is_in_int_range(days, 1, 365):
        raise InvalidQuery("days")

    nodes, edges = _snapshot()
    by_id = {n.node_id: n for n in nodes}
    now = _now()
    since = now - timedelta(days=days)

    # Tables that BELONG_TO the focus database.
    tables = {
        e.source_id
        for e in edges
        if e.edge_type == "BELONGS_TO" and e.target_id == database_node_id
    }

    result_nodes: dict[str, GraphNode] = {}
    result_edges: list[GraphEdge] = []

    db_node = by_id.get(database_node_id)
    if db_node is not None:
        result_nodes[database_node_id] = db_node

    # ChangeEvents that RUN_AGAINST one of those tables, filtered to DDL+window.
    matched_ce: set[str] = set()
    for e in edges:
        if e.edge_type != "RUNS_AGAINST" or e.target_id not in tables:
            continue
        ce = by_id.get(e.source_id)
        if ce is None or ce.props.get("ddl_kind") is None:
            continue
        cts = _contributing_ts(ce)
        if cts is None or cts < since:
            continue
        matched_ce.add(ce.node_id)
        result_nodes[ce.node_id] = ce
        # The table + the RUNS_AGAINST / BELONGS_TO edges that connect it.
        table_node = by_id.get(e.target_id)
        if table_node is not None:
            result_nodes[table_node.node_id] = table_node
        result_edges.append(e)

    # BELONGS_TO edges from the included tables to the database.
    for e in edges:
        if (
            e.edge_type == "BELONGS_TO"
            and e.target_id == database_node_id
            and e.source_id in result_nodes
        ):
            result_edges.append(e)

    # MODIFIED_BY principals and CAUSED_BY tickets for the matched events.
    for e in edges:
        if e.source_id not in matched_ce:
            continue
        if e.edge_type in ("MODIFIED_BY", "CAUSED_BY"):
            target = by_id.get(e.target_id)
            if target is not None:
                result_nodes[e.target_id] = target
                result_edges.append(e)

    return _materialize(result_nodes, result_edges, database_node_id, since, now)


def ticket_changes(ticket_node_id: str, days: int) -> GraphResult:
    """Every ChangeEvent CAUSED_BY ``ticket_node_id`` within the window (R8.3)."""
    if not _is_in_int_range(days, 1, 365):
        raise InvalidQuery("days")

    nodes, edges = _snapshot()
    by_id = {n.node_id: n for n in nodes}
    now = _now()
    since = now - timedelta(days=days)

    result_nodes: dict[str, GraphNode] = {}
    result_edges: list[GraphEdge] = []

    ticket_node = by_id.get(ticket_node_id)
    if ticket_node is not None:
        result_nodes[ticket_node_id] = ticket_node

    for e in edges:
        if e.edge_type != "CAUSED_BY" or e.target_id != ticket_node_id:
            continue
        ce = by_id.get(e.source_id)
        if ce is None:
            continue
        cts = _contributing_ts(ce)
        if cts is None or cts < since:
            continue
        result_nodes[ce.node_id] = ce
        result_edges.append(e)

    return _materialize(result_nodes, result_edges, ticket_node_id, since, now)


def principal_changes(principal_node_id: str, days: int) -> GraphResult:
    """Every ChangeEvent MODIFIED_BY ``principal_node_id`` within window (R8.3)."""
    if not _is_in_int_range(days, 1, 365):
        raise InvalidQuery("days")

    nodes, edges = _snapshot()
    by_id = {n.node_id: n for n in nodes}
    now = _now()
    since = now - timedelta(days=days)

    result_nodes: dict[str, GraphNode] = {}
    result_edges: list[GraphEdge] = []

    principal_node = by_id.get(principal_node_id)
    if principal_node is not None:
        result_nodes[principal_node_id] = principal_node

    for e in edges:
        if e.edge_type != "MODIFIED_BY" or e.target_id != principal_node_id:
            continue
        ce = by_id.get(e.source_id)
        if ce is None:
            continue
        cts = _contributing_ts(ce)
        if cts is None or cts < since:
            continue
        result_nodes[ce.node_id] = ce
        result_edges.append(e)

    return _materialize(result_nodes, result_edges, principal_node_id, since, now)


def unticketed_changes(days: int) -> UnticketedResult:
    """High/critical DDL ChangeEvents with no CAUSED_BY ticket, in window (R7.4).

    A ChangeEvent ``c`` is returned IFF ``c.severity in {high, critical}`` AND
    ``c.ddl_kind`` is set AND ``c.contributing_ts`` is within the window AND
    ``c`` has no ``CAUSED_BY`` edge to any ``Ticket`` node (P-KG7).

    The in-memory backend is authoritative, so ``complete`` is True. The
    ``complete=False`` / ``reason`` path is reserved for the future
    Neptune/ingestion-lag case (R7.4 partial-result rule).
    """
    if not _is_in_int_range(days, 1, 365):
        raise InvalidQuery("days")

    nodes, edges = _snapshot()
    by_id = {n.node_id: n for n in nodes}
    since = _now() - timedelta(days=days)

    # ChangeEvent ids that have a CAUSED_BY edge to a Ticket node.
    ticketed: set[str] = set()
    for e in edges:
        if e.edge_type != "CAUSED_BY":
            continue
        target = by_id.get(e.target_id)
        if target is not None and target.type == "Ticket":
            ticketed.add(e.source_id)

    events: list[GraphNode] = []
    for node in nodes:
        if node.type != "ChangeEvent":
            continue
        if node.props.get("severity") not in _UNTICKETED_SEVERITIES:
            continue
        if node.props.get("ddl_kind") is None:
            continue
        cts = _contributing_ts(node)
        if cts is None or cts < since:
            continue
        if node.node_id in ticketed:
            continue
        events.append(node)

    events.sort(key=lambda n: n.node_id)
    return UnticketedResult(events=events, complete=True)


def _materialize(
    result_nodes: dict[str, GraphNode],
    result_edges: list[GraphEdge],
    focus: str,
    since: datetime,
    now: datetime,
) -> GraphResult:
    """Build a deterministic :class:`GraphResult` from collected nodes/edges."""
    ordered_nodes = [result_nodes[k] for k in sorted(result_nodes)]
    # Dedup edges (a (src, type, tgt) may be collected more than once) + sort.
    edge_keys = {(e.source_id, e.edge_type, e.target_id) for e in result_edges}
    ordered_edges = [
        GraphEdge(edge_type=etype, source_id=src, target_id=tgt)
        for (src, etype, tgt) in sorted(edge_keys)
    ]
    return GraphResult(
        nodes=ordered_nodes,
        edges=ordered_edges,
        focus=focus,
        window=_window(since, now),
    )
