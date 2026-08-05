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

"""Property P-KG5 (R1.5, R1.6, R7.5, R9.4) — graph read-only invariant.

After any sequence of DBA View graph reads (connected / database_ddl_activity /
ticket_changes / principal_changes / unticketed_changes), the backing store is
byte-for-byte unchanged: no node is added/removed/mutated and no edge is
added/removed. The query layer exposes no write verb at all — there is no
upsert/delete entry point on the read surface — so a "write attempt via a graph
endpoint" is structurally impossible and is asserted here by confirming the
read API surface contains no mutators.
"""

from __future__ import annotations

import hashlib

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg import query, store as store_mod
from src.admin_ops.kg.ingest import map_change_event
from src.admin_ops.kg.query import (
    TraversalParams,
    connected,
    database_ddl_activity,
    principal_changes,
    ticket_changes,
    unticketed_changes,
)
from src.admin_ops.kg.store import InMemoryGraphBackend
from tests.admin_ops.kg._inmemory import ACCOUNT_KEY, StubLinkage, change_events

_LINKAGE = StubLinkage(
    by_resource_pattern=[
        (r"shop\.orders", "CHG-1042"),
        (r"shop\.order_items", "CHG-1043"),
        (r"public\.users", "CHG-1044"),
    ]
)


def _fingerprint(backend: InMemoryGraphBackend) -> str:
    """Stable hash of the full store state (nodes + edges + props)."""
    nodes = sorted(
        (
            n.node_id,
            n.type,
            n.label,
            tuple(sorted((k, repr(v)) for k, v in n.props.items())),
        )
        for n in backend.iter_nodes()
    )
    edges = sorted((e.source_id, e.edge_type, e.target_id) for e in backend.iter_edges())
    h = hashlib.sha256()
    h.update(repr(nodes).encode())
    h.update(repr(edges).encode())
    return h.hexdigest()


def _seed(events) -> InMemoryGraphBackend:
    backend = InMemoryGraphBackend()
    for e in events:
        backend.upsert(map_change_event(e, ticket_linkage=_LINKAGE, account_key=ACCOUNT_KEY))
    store_mod.set_backend_for_testing(backend)
    return backend


# Feature: dba-knowledge-graph, Property P-KG5: graph read-only invariant
@settings(deadline=None, max_examples=150)
@given(events=st.lists(change_events(), min_size=1, max_size=20))
def test_pkg5_reads_do_not_mutate_the_store(events) -> None:
    backend = _seed(events)
    try:
        before = _fingerprint(backend)

        # Drive every read query. Use a known focus (the first node) for
        # connected; the specialized queries scan the whole graph.
        any_node = backend.iter_nodes()[0].node_id
        connected(TraversalParams(focus_node_id=any_node, hops=3, days=365))
        for n in backend.iter_nodes():
            if n.type == "Database":
                database_ddl_activity(n.node_id, days=365)
            elif n.type == "Ticket":
                ticket_changes(n.node_id, days=365)
            elif n.type == "Principal":
                principal_changes(n.node_id, days=365)
        unticketed_changes(days=365)

        after = _fingerprint(backend)
        assert before == after
    finally:
        store_mod.set_backend_for_testing(None)


def test_pkg5_query_module_exposes_no_write_verb() -> None:
    """The read surface has no mutator (no write endpoint to attack, R9.4)."""
    import src.admin_ops.kg.query as q

    forbidden = {"upsert", "delete", "put", "write", "set_node", "remove", "prune"}
    public = {name for name in dir(q) if not name.startswith("_")}
    assert public.isdisjoint(forbidden), public & forbidden
