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

"""Property S2 (R5.1, R5.5, R5.7, R8.3) — traversal/query soundness + shape.

Builds a random graph in an InMemoryGraphBackend (via map_change_event over
change_events()), then:

* every node returned by ``connected`` is reachable from the focus within hops
  and (for ChangeEvent nodes) within the window; every node carries
  type/node_id/label and every edge carries edge_type/source_id/target_id;
* ``database_ddl_activity`` / ``ticket_changes`` / ``principal_changes`` return
  exactly their defined sets.

A fixed "now" is patched in so the time window is deterministic.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from unittest import mock

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg import query, store as store_mod
from src.admin_ops.kg.ingest import map_change_event
from src.admin_ops.kg.model import GraphEdge, GraphNode, make_node_id
from src.admin_ops.kg.query import (
    TraversalParams,
    connected,
    database_ddl_activity,
    principal_changes,
    ticket_changes,
)
from src.admin_ops.kg.store import InMemoryGraphBackend
from tests.admin_ops.kg._inmemory import ACCOUNT_KEY, StubLinkage, change_events

# All generated event timestamps are <= 2030-01-01, so this "now" is strictly
# after every event and the day-window arithmetic is clean.
_FIXED_NOW = datetime(2030, 1, 2, 0, 0, 0, tzinfo=timezone.utc)

# Linkage so some events get CAUSED_BY edges to seeded Ticket nodes.
_LINKAGE = StubLinkage(
    by_resource_pattern=[
        (r"shop\.orders", "CHG-1042"),
        (r"shop\.order_items", "CHG-1043"),
        (r"public\.users", "CHG-1044"),
    ]
)


def _seed(events) -> InMemoryGraphBackend:
    backend = InMemoryGraphBackend()
    for e in events:
        backend.upsert(map_change_event(e, ticket_linkage=_LINKAGE, account_key=ACCOUNT_KEY))
    store_mod.set_backend_for_testing(backend)
    return backend


def _full_shape_ok(nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
    for n in nodes:
        assert n.node_id
        assert n.type
        assert n.label is not None
    for e in edges:
        assert e.edge_type
        assert e.source_id
        assert e.target_id


def _reachable_within_hops(
    backend: InMemoryGraphBackend, focus: str, hops: int
) -> set[str]:
    """Undirected BFS over all edges, bounded by hops, ignoring the window.

    This is an UPPER BOUND on what ``connected`` may return; the window only
    removes nodes, never adds.
    """
    edges = backend.iter_edges()
    reachable: set[str] = {focus}
    frontier: deque[tuple[str, int]] = deque([(focus, 0)])
    seen = {focus}
    while frontier:
        cur, depth = frontier.popleft()
        if depth >= hops:
            continue
        for e in edges:
            nxt = None
            if e.source_id == cur:
                nxt = e.target_id
            elif e.target_id == cur:
                nxt = e.source_id
            if nxt is None:
                continue
            reachable.add(nxt)
            if nxt not in seen:
                seen.add(nxt)
                frontier.append((nxt, depth + 1))
    return reachable


def _cts(node: GraphNode) -> datetime | None:
    raw = node.props.get("contributing_ts")
    if node.type != "ChangeEvent" or not isinstance(raw, str):
        return None
    return datetime.fromisoformat(raw)


# Feature: dba-knowledge-graph, Property S2: traversal soundness + full shape
@settings(deadline=None, max_examples=200)
@given(
    events=st.lists(change_events(), max_size=20),
    hops=st.integers(min_value=1, max_value=3),
    days=st.integers(min_value=1, max_value=365),
    idx=st.integers(min_value=0, max_value=10_000),
)
def test_s2_connected_soundness(events, hops: int, days: int, idx: int) -> None:
    backend = _seed(events)
    try:
        node_ids = sorted({n.node_id for n in backend.iter_nodes()})
        if not node_ids:
            # Missing focus -> InvalidQuery (covered by S3); skip soundness.
            return
        focus = node_ids[idx % len(node_ids)]
        with mock.patch.object(query, "_now", return_value=_FIXED_NOW):
            result = connected(TraversalParams(focus_node_id=focus, hops=hops, days=days))

        since = _FIXED_NOW - timedelta(days=days)
        reachable = _reachable_within_hops(backend, focus, hops)
        _full_shape_ok(result.nodes, result.edges)

        for n in result.nodes:
            assert n.node_id in reachable  # within hops
            cts = _cts(n)
            if cts is not None:
                assert cts >= since  # in-window
        # Every returned edge endpoint is reachable within hops (the edge was
        # traversed). Note: the Phase-3 backend may return an edge incident to
        # the focus even when the focus itself is an out-of-window ChangeEvent
        # (excluded from nodes), so we check reachability, not node-set membership.
        for e in result.edges:
            assert e.source_id in reachable
            assert e.target_id in reachable
        assert result.focus == focus
        assert "from" in result.window
    finally:
        store_mod.set_backend_for_testing(None)


# Feature: dba-knowledge-graph, Property S2: specialized queries return exact sets
@settings(deadline=None, max_examples=200)
@given(
    events=st.lists(change_events(), max_size=20),
    days=st.integers(min_value=1, max_value=365),
)
def test_s2_specialized_queries_exact_sets(events, days: int) -> None:
    backend = _seed(events)
    try:
        nodes = backend.iter_nodes()
        edges = backend.iter_edges()
        by_id = {n.node_id: n for n in nodes}
        since = _FIXED_NOW - timedelta(days=days)

        def in_window(ce_id: str) -> bool:
            cts = _cts(by_id[ce_id])
            return cts is not None and cts >= since

        # --- database_ddl_activity ---
        db_id = make_node_id("Database", "database-test")
        tables = {
            e.source_id
            for e in edges
            if e.edge_type == "BELONGS_TO" and e.target_id == db_id
        }
        matched_ce = {
            e.source_id
            for e in edges
            if e.edge_type == "RUNS_AGAINST"
            and e.target_id in tables
            and by_id[e.source_id].props.get("ddl_kind") is not None
            and in_window(e.source_id)
        }
        expected_nodes = set(matched_ce)
        if db_id in by_id:
            expected_nodes.add(db_id)
        for e in edges:
            if e.source_id in matched_ce and e.edge_type == "RUNS_AGAINST":
                expected_nodes.add(e.target_id)
            if e.source_id in matched_ce and e.edge_type in ("MODIFIED_BY", "CAUSED_BY"):
                expected_nodes.add(e.target_id)

        with mock.patch.object(query, "_now", return_value=_FIXED_NOW):
            ddl_result = database_ddl_activity(db_id, days)

        result_ce = {n.node_id for n in ddl_result.nodes if n.type == "ChangeEvent"}
        assert result_ce == matched_ce
        assert {n.node_id for n in ddl_result.nodes} == expected_nodes
        _full_shape_ok(ddl_result.nodes, ddl_result.edges)

        # --- ticket_changes ---
        ticket_id = make_node_id("Ticket", "CHG-1042")
        expected_ticket_ce = {
            e.source_id
            for e in edges
            if e.edge_type == "CAUSED_BY"
            and e.target_id == ticket_id
            and in_window(e.source_id)
        }
        with mock.patch.object(query, "_now", return_value=_FIXED_NOW):
            tk_result = ticket_changes(ticket_id, days)
        tk_ce = {n.node_id for n in tk_result.nodes if n.type == "ChangeEvent"}
        assert tk_ce == expected_ticket_ce
        expected_tk_nodes = set(expected_ticket_ce)
        if ticket_id in by_id:
            expected_tk_nodes.add(ticket_id)
        assert {n.node_id for n in tk_result.nodes} == expected_tk_nodes

        # --- principal_changes ---
        principal_ids = sorted(n.node_id for n in nodes if n.type == "Principal")
        principal_id = principal_ids[0] if principal_ids else make_node_id("Principal", "nobody")
        expected_principal_ce = {
            e.source_id
            for e in edges
            if e.edge_type == "MODIFIED_BY"
            and e.target_id == principal_id
            and in_window(e.source_id)
        }
        with mock.patch.object(query, "_now", return_value=_FIXED_NOW):
            pr_result = principal_changes(principal_id, days)
        pr_ce = {n.node_id for n in pr_result.nodes if n.type == "ChangeEvent"}
        assert pr_ce == expected_principal_ce
        expected_pr_nodes = set(expected_principal_ce)
        if principal_id in by_id:
            expected_pr_nodes.add(principal_id)
        assert {n.node_id for n in pr_result.nodes} == expected_pr_nodes
    finally:
        store_mod.set_backend_for_testing(None)
