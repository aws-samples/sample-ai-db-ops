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

"""Property P-KG7 (R7.4) — unticketed-change detection soundness.

For any graph state G and window W, ``unticketed_changes`` returns a ChangeEvent
node c IFF c.severity in {high, critical} AND c.ddl_kind is set AND
c.contributing_ts in W AND c has NO CAUSED_BY edge to any Ticket node.

Graphs are synthesized directly so each ChangeEvent's severity, ddl_kind,
timestamp, and ticketing are controlled independently; a fixed "now" makes the
window deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg import query, store as store_mod
from src.admin_ops.kg.ingest import GraphMutation
from src.admin_ops.kg.model import GraphEdge, GraphNode, make_node_id
from src.admin_ops.kg.query import unticketed_changes
from src.admin_ops.kg.store import InMemoryGraphBackend

_FIXED_NOW = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
_SEVERITIES = ["low", "medium", "high", "critical"]
_DDL_KINDS = [None, "ALTER", "TRUNCATE", "CREATE", "DROP"]


@st.composite
def event_specs(draw: st.DrawFn) -> dict:
    """One synthetic ChangeEvent spec with independent attributes."""
    return {
        "severity": draw(st.sampled_from(_SEVERITIES)),
        "ddl_kind": draw(st.sampled_from(_DDL_KINDS)),
        # age_days: how far before _FIXED_NOW the event happened (some negative
        # => "in the future" relative to now, which is also out of window).
        "age_days": draw(st.integers(min_value=-10, max_value=800)),
        "ticketed": draw(st.booleans()),
    }


def _build(specs: list[dict]) -> InMemoryGraphBackend:
    backend = InMemoryGraphBackend()
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    for i, spec in enumerate(specs):
        ts = _FIXED_NOW - timedelta(days=spec["age_days"])
        eid = f"evt-{i}"
        ce_id = make_node_id("ChangeEvent", eid)
        props: dict = {
            "event_id": eid,
            "source": "database",
            "severity": spec["severity"],
            "timestamp": ts.isoformat(),
            "contributing_ts": ts.isoformat(),
            "summary": "synthetic",
            "details_url": "https://example.com/x",
        }
        if spec["ddl_kind"] is not None:
            props["ddl_kind"] = spec["ddl_kind"]
        nodes.append(GraphNode(node_id=ce_id, type="ChangeEvent", label="synthetic", props=props))
        if spec["ticketed"]:
            ticket_id = make_node_id("Ticket", f"CHG-{i}")
            nodes.append(
                GraphNode(
                    node_id=ticket_id,
                    type="Ticket",
                    label=f"CHG-{i}",
                    props={"ticket_id": f"CHG-{i}"},
                )
            )
            edges.append(
                GraphEdge(edge_type="CAUSED_BY", source_id=ce_id, target_id=ticket_id)
            )
    backend.upsert(GraphMutation(nodes=nodes, edges=edges))
    return backend


# Feature: dba-knowledge-graph, Property P-KG7: unticketed-change detection soundness
@settings(deadline=None, max_examples=200)
@given(
    specs=st.lists(event_specs(), max_size=20),
    days=st.integers(min_value=1, max_value=365),
)
def test_p_kg7_unticketed_iff(specs: list[dict], days: int) -> None:
    backend = _build(specs)
    store_mod.set_backend_for_testing(backend)
    try:
        with mock.patch.object(query, "_now", return_value=_FIXED_NOW):
            result = unticketed_changes(days)

        since = _FIXED_NOW - timedelta(days=days)
        returned = {n.node_id for n in result.events}

        for i, spec in enumerate(specs):
            ce_id = make_node_id("ChangeEvent", f"evt-{i}")
            ts = _FIXED_NOW - timedelta(days=spec["age_days"])
            expected = (
                spec["severity"] in {"high", "critical"}
                and spec["ddl_kind"] is not None
                and ts >= since
                and not spec["ticketed"]
            )
            assert (ce_id in returned) == expected

        # In-memory backend is authoritative.
        assert result.complete is True
        assert result.reason is None
        # Only ChangeEvent nodes are reported.
        for n in result.events:
            assert n.type == "ChangeEvent"
    finally:
        store_mod.set_backend_for_testing(None)


# Feature: dba-knowledge-graph, Property P-KG7: a ticketed qualifying change is excluded
def test_p_kg7_ticketed_change_excluded() -> None:
    specs = [{"severity": "critical", "ddl_kind": "DROP", "age_days": 1, "ticketed": True}]
    backend = _build(specs)
    store_mod.set_backend_for_testing(backend)
    try:
        with mock.patch.object(query, "_now", return_value=_FIXED_NOW):
            result = unticketed_changes(30)
        assert result.events == []
    finally:
        store_mod.set_backend_for_testing(None)


# Feature: dba-knowledge-graph, Property P-KG7: a qualifying unticketed change is reported
def test_p_kg7_qualifying_unticketed_reported() -> None:
    specs = [{"severity": "high", "ddl_kind": "ALTER", "age_days": 5, "ticketed": False}]
    backend = _build(specs)
    store_mod.set_backend_for_testing(backend)
    try:
        with mock.patch.object(query, "_now", return_value=_FIXED_NOW):
            result = unticketed_changes(30)
        assert [n.node_id for n in result.events] == [make_node_id("ChangeEvent", "evt-0")]
        assert result.complete is True
    finally:
        store_mod.set_backend_for_testing(None)
