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

"""Property S4 (R6.3, R6.4) — Filter predicate soundness (AND across, OR within).

For any list of events and any filter selection across the categories database,
principal, severity, source, and time range, the returned set is exactly the
events satisfying every selected category (AND across) and any selected value
within a category (OR within); the DDL-only toggle restricts to events whose
``ddl_kind`` is set.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg.filters import (
    EventFilter,
    apply,
    event_database,
    event_principal,
)
from src.admin_ops.kg.ingest import ddl_kind_of
from tests.admin_ops.kg._inmemory import change_events

_SEVERITIES = ["low", "medium", "high", "critical"]
_SOURCES = ["git", "cloudtrail", "agent", "database"]
_DBS = ["database-test", "shop-db", "orders-db"]
_ACTORS = ["appuser@appdb", "dbops@postgres", "alice", "bob", "agent-x"]


def _filters() -> st.SearchStrategy[EventFilter]:
    opt = lambda values: st.one_of(  # noqa: E731
        st.none(), st.lists(st.sampled_from(values), max_size=4, unique=True)
    )
    return st.builds(
        EventFilter,
        databases=opt(_DBS),
        principals=opt(_ACTORS),
        severities=opt(_SEVERITIES),
        sources=opt(_SOURCES),
        ddl_only=st.booleans(),
    )


def _expected(f: EventFilter, e) -> bool:
    """Reference predicate: AND across active categories, OR within each."""
    if f.databases is not None and event_database(e) not in f.databases:
        return False
    if f.principals is not None and event_principal(e) not in f.principals:
        return False
    if f.severities is not None and e.severity not in f.severities:
        return False
    if f.sources is not None and e.source not in f.sources:
        return False
    if f.ddl_only and ddl_kind_of(e) is None:
        return False
    return True


# Feature: dba-knowledge-graph, Property S4: filter predicate soundness
@settings(deadline=None, max_examples=200)
@given(events=st.lists(change_events(), max_size=15), f=_filters())
def test_s4_returned_set_is_exactly_the_satisfying_events(
    events: list, f: EventFilter
) -> None:
    got = {e.event_id for e in apply(f, events)}
    want = {e.event_id for e in events if _expected(f, e)}
    assert got == want


# Feature: dba-knowledge-graph, Property S4: ddl_only restricts to DDL events
@settings(deadline=None, max_examples=200)
@given(events=st.lists(change_events(), max_size=15))
def test_s4_ddl_only_yields_only_ddl_events(events: list) -> None:
    out = apply(EventFilter(ddl_only=True), events)
    for e in out:
        assert ddl_kind_of(e) is not None


# Feature: dba-knowledge-graph, Property S4: empty filter is the identity set
@settings(deadline=None, max_examples=100)
@given(events=st.lists(change_events(), max_size=15))
def test_s4_inactive_filter_returns_all(events: list) -> None:
    out = apply(EventFilter(), events)
    assert [e.event_id for e in out] == [e.event_id for e in events]
