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

"""Property S1 (R2.3, R2.4, R3.4, R3.7, R7.2, R8.4) — ingestion mapping correctness.

For any ChangeEvent e, map_change_event(e) emits:
* exactly one ChangeEvent:{e.event_id} node carrying event_id/source/severity/
  timestamp (and ddl_kind iff DDL);
* exactly one MODIFIED_BY edge to Principal:{e.actor};
* a RUNS_AGAINST + BELONGS_TO + OWNS chain iff a table is identifiable;
* a CAUSED_BY edge iff the (stub) linkage resolves a ticket.
The mapper is pure, so it is exercised with no backend.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg.ingest import ddl_kind_of, map_change_event, parse_resource
from src.admin_ops.kg.model import make_node_id
from tests.admin_ops.kg._inmemory import (
    ACCOUNT_KEY,
    StubLinkage,
    change_events,
)


def _nodes_by_type(mutation, t):
    return [n for n in mutation.nodes if n.type == t]


def _edges_of_type(mutation, et):
    return [e for e in mutation.edges if e.edge_type == et]


# Feature: dba-knowledge-graph, Property S1: ingestion mapping correctness
@settings(deadline=None, max_examples=200)
@given(event=change_events(), link_ticket=st.booleans())
def test_s1_mapping_correctness(event, link_ticket: bool) -> None:
    # When link_ticket, register an exact event_id -> ticket linkage.
    linkage = (
        StubLinkage(by_event_id={event.event_id: "CHG-1042"})
        if link_ticket
        else StubLinkage()
    )
    mutation = map_change_event(event, ticket_linkage=linkage, account_key=ACCOUNT_KEY)

    # Exactly one ChangeEvent node, keyed correctly, with the required props.
    ce_nodes = _nodes_by_type(mutation, "ChangeEvent")
    assert len(ce_nodes) == 1
    ce = ce_nodes[0]
    assert ce.node_id == make_node_id("ChangeEvent", event.event_id)
    assert ce.props["event_id"] == event.event_id
    assert ce.props["source"] == event.source
    assert ce.props["severity"] == event.severity
    assert ce.props["timestamp"] == event.timestamp.isoformat()

    # ddl_kind set iff DDL.
    kind = ddl_kind_of(event)
    if kind is None:
        assert "ddl_kind" not in ce.props
    else:
        assert ce.props["ddl_kind"] == kind

    # Exactly one Principal node and exactly one MODIFIED_BY edge to it.
    principal_nodes = _nodes_by_type(mutation, "Principal")
    assert len(principal_nodes) == 1
    principal_id = make_node_id("Principal", event.actor)
    assert principal_nodes[0].node_id == principal_id
    modified_by = _edges_of_type(mutation, "MODIFIED_BY")
    assert len(modified_by) == 1
    assert modified_by[0].source_id == ce.node_id
    assert modified_by[0].target_id == principal_id

    # Table chain iff a table is identifiable.
    db, table = parse_resource(event)
    runs_against = _edges_of_type(mutation, "RUNS_AGAINST")
    belongs_to = _edges_of_type(mutation, "BELONGS_TO")
    owns = _edges_of_type(mutation, "OWNS")
    if table is not None:
        assert db is not None
        table_id = make_node_id("Table", f"{db}:{table}")
        db_id = make_node_id("Database", db)
        account_id = make_node_id("Account", ACCOUNT_KEY)
        assert len(runs_against) == 1
        assert runs_against[0].source_id == ce.node_id
        assert runs_against[0].target_id == table_id
        assert len(belongs_to) == 1
        assert belongs_to[0].source_id == table_id
        assert belongs_to[0].target_id == db_id
        assert len(owns) == 1
        assert owns[0].source_id == account_id
        assert owns[0].target_id == db_id
    else:
        assert runs_against == []
        assert belongs_to == []
        # OWNS only exists when a db is identifiable.
        if db is None:
            assert owns == []

    # CAUSED_BY edge iff linkage resolves a ticket.
    caused_by = _edges_of_type(mutation, "CAUSED_BY")
    if link_ticket:
        assert len(caused_by) == 1
        assert caused_by[0].source_id == ce.node_id
        assert caused_by[0].target_id == make_node_id("Ticket", "CHG-1042")
        assert len(_nodes_by_type(mutation, "Ticket")) == 1
    else:
        assert caused_by == []
        assert _nodes_by_type(mutation, "Ticket") == []


# Feature: dba-knowledge-graph, Property S1: referential safety of the mutation
@settings(deadline=None, max_examples=200)
@given(event=change_events(), link_ticket=st.booleans())
def test_s1_every_edge_endpoint_is_a_node(event, link_ticket: bool) -> None:
    linkage = (
        StubLinkage(by_event_id={event.event_id: "CHG-1042"})
        if link_ticket
        else StubLinkage()
    )
    mutation = map_change_event(event, ticket_linkage=linkage, account_key=ACCOUNT_KEY)
    node_ids = {n.node_id for n in mutation.nodes}
    for edge in mutation.edges:
        assert edge.source_id in node_ids
        assert edge.target_id in node_ids


def test_resource_pattern_linkage_resolves_ticket() -> None:
    # A database DDL event on shop.orders linked by a resource_id regex.
    from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
    from datetime import datetime, timezone

    ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    resource_id = "pg_ddl:database-test:TABLE shop.orders"
    event = ChangeEvent(
        event_id=make_event_id("database", "appuser@appdb", ts, resource_id),
        source="database",
        actor="appuser@appdb",
        timestamp=ts,
        engine="postgresql",
        resource_id=resource_id,
        severity="high",
        summary="ALTER on TABLE shop.orders (database-test): ALTER ...",
        details_url="cloudwatch:postgresql:database-test",
        raw_payload_ref="pgddl:stream:1",
    )
    linkage = StubLinkage(by_resource_pattern=[(r"shop\.orders", "CHG-1042")])
    mutation = map_change_event(event, ticket_linkage=linkage, account_key=ACCOUNT_KEY)
    caused_by = _edges_of_type(mutation, "CAUSED_BY")
    assert len(caused_by) == 1
    assert caused_by[0].target_id == make_node_id("Ticket", "CHG-1042")


def test_event_id_match_takes_priority_over_pattern() -> None:
    from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
    from datetime import datetime, timezone

    ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    resource_id = "pg_ddl:database-test:TABLE shop.orders"
    event = ChangeEvent(
        event_id=make_event_id("database", "appuser@appdb", ts, resource_id),
        source="database",
        actor="appuser@appdb",
        timestamp=ts,
        engine="postgresql",
        resource_id=resource_id,
        severity="high",
        summary="ALTER on TABLE shop.orders (database-test): ALTER ...",
        details_url="cloudwatch:postgresql:database-test",
        raw_payload_ref="pgddl:stream:1",
    )
    linkage = StubLinkage(
        by_event_id={event.event_id: "CHG-2000"},
        by_resource_pattern=[(r"shop\.orders", "CHG-1042")],
    )
    mutation = map_change_event(event, ticket_linkage=linkage, account_key=ACCOUNT_KEY)
    caused_by = _edges_of_type(mutation, "CAUSED_BY")
    assert caused_by[0].target_id == make_node_id("Ticket", "CHG-2000")


def test_no_linkage_argument_defaults_to_no_ticket() -> None:
    from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
    from datetime import datetime, timezone

    ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    event = ChangeEvent(
        event_id=make_event_id("git", "alice", ts, "config.yaml"),
        source="git",
        actor="alice",
        timestamp=ts,
        engine=None,
        resource_id="config.yaml",
        severity="low",
        summary="touched config",
        details_url="https://example.com/x",
        raw_payload_ref="ref",
    )
    mutation = map_change_event(event, account_key=ACCOUNT_KEY)
    assert _edges_of_type(mutation, "CAUSED_BY") == []
