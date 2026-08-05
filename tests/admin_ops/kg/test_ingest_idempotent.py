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

"""Property P-KG1 (R2.5, R2.8, R3.6) — graph ingestion idempotence.

Ingesting e twice via store.upsert(map_change_event(e)) yields the same node
set, edge set, and property values as ingesting it once; node_id is stable.
Exercised across all four sources, DDL + non-DDL, against InMemoryGraphBackend.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg.ingest import map_change_event
from src.admin_ops.kg.store import InMemoryGraphBackend
from tests.admin_ops.kg._inmemory import ACCOUNT_KEY, StubLinkage, change_events


def _snapshot(backend: InMemoryGraphBackend) -> tuple[dict, set]:
    # node_id -> (type, label, sorted props items); plus the edge key set.
    nodes = {
        nid: (n.type, n.label, tuple(sorted(n.props.items())))
        for nid, n in backend._nodes.items()
    }
    return nodes, set(backend._edges)


# Feature: dba-knowledge-graph, Property P-KG1: graph ingestion idempotence
@settings(deadline=None, max_examples=200)
@given(event=change_events(), link_ticket=st.booleans())
def test_p_kg1_ingestion_idempotent(event, link_ticket: bool) -> None:
    linkage = (
        StubLinkage(by_event_id={event.event_id: "CHG-1042"})
        if link_ticket
        else StubLinkage()
    )
    mutation = map_change_event(event, ticket_linkage=linkage, account_key=ACCOUNT_KEY)

    once = InMemoryGraphBackend()
    once.upsert(mutation)
    once_snap = _snapshot(once)

    twice = InMemoryGraphBackend()
    twice.upsert(mutation)
    twice.upsert(mutation)
    twice_snap = _snapshot(twice)

    assert once_snap == twice_snap


# Feature: dba-knowledge-graph, Property P-KG1: node_id stable across re-mapping
@settings(deadline=None, max_examples=200)
@given(event=change_events())
def test_p_kg1_node_ids_stable_across_remapping(event) -> None:
    m1 = map_change_event(event, account_key=ACCOUNT_KEY)
    m2 = map_change_event(event, account_key=ACCOUNT_KEY)
    assert {n.node_id for n in m1.nodes} == {n.node_id for n in m2.nodes}
    # And ingesting both into one backend does not grow it beyond one ingest.
    b = InMemoryGraphBackend()
    b.upsert(m1)
    snap1 = _snapshot(b)
    b.upsert(m2)
    assert _snapshot(b) == snap1
