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

"""Property P-KG2 (R2.9, R3.5, R10.6) — graph-event referential integrity.

For any set S of ChangeEvents and G = ingest_all(S): every edge's source and
target node exist in G, and each event_id is represented by exactly one
ChangeEvent node. Run against InMemoryGraphBackend.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg.ingest import map_change_event
from src.admin_ops.kg.model import make_node_id
from src.admin_ops.kg.store import InMemoryGraphBackend
from tests.admin_ops.kg._inmemory import ACCOUNT_KEY, StubLinkage, change_events


# Feature: dba-knowledge-graph, Property P-KG2: graph-event referential integrity
@settings(deadline=None, max_examples=200)
@given(
    events=st.lists(change_events(), max_size=25),
    link_all=st.booleans(),
)
def test_p_kg2_referential_integrity(events, link_all: bool) -> None:
    backend = InMemoryGraphBackend()
    for e in events:
        linkage = (
            StubLinkage(by_event_id={e.event_id: "CHG-1042"})
            if link_all
            else StubLinkage()
        )
        backend.upsert(
            map_change_event(e, ticket_linkage=linkage, account_key=ACCOUNT_KEY)
        )

    node_ids = set(backend._nodes)
    # Every edge endpoint exists as a node.
    for src, _etype, tgt in backend._edges:
        assert src in node_ids
        assert tgt in node_ids

    # Each event_id is represented by exactly one ChangeEvent node.
    distinct_event_ids = {e.event_id for e in events}
    ce_nodes = [n for n in backend._nodes.values() if n.type == "ChangeEvent"]
    ce_ids = [n.node_id for n in ce_nodes]
    assert len(ce_ids) == len(set(ce_ids))  # no duplicates
    assert set(ce_ids) == {make_node_id("ChangeEvent", eid) for eid in distinct_event_ids}


# Feature: dba-knowledge-graph, Property P-KG2: each event_id -> one ChangeEvent node
@settings(deadline=None, max_examples=200)
@given(events=st.lists(change_events(), min_size=1, max_size=25))
def test_p_kg2_event_id_count_matches_distinct(events) -> None:
    backend = InMemoryGraphBackend()
    for e in events:
        backend.upsert(map_change_event(e, account_key=ACCOUNT_KEY))
    ce_count = sum(1 for n in backend._nodes.values() if n.type == "ChangeEvent")
    assert ce_count == len({e.event_id for e in events})
