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

"""Property P-KG4 (R6.5) — Explorer filter compositionality.

For any list of ChangeEvents L and any pair of filters f1, f2:
``apply(f2, apply(f1, L)) == apply(f1, apply(f2, L))`` — filter order does not
change the result set (confluence), mirroring AOC P11.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg.filters import EventFilter, apply
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


# Feature: dba-knowledge-graph, Property P-KG4: explorer filter compositionality
@settings(deadline=None, max_examples=200)
@given(
    events=st.lists(change_events(), max_size=12),
    f1=_filters(),
    f2=_filters(),
)
def test_pkg4_filter_composition_is_confluent(
    events: list, f1: EventFilter, f2: EventFilter
) -> None:
    left = apply(f2, apply(f1, events))
    right = apply(f1, apply(f2, events))
    # Order-preserving predicate filters compose confluently.
    assert [e.event_id for e in left] == [e.event_id for e in right]


# Feature: dba-knowledge-graph, Property P-KG4: single filter is idempotent
@settings(deadline=None, max_examples=200)
@given(events=st.lists(change_events(), max_size=12), f=_filters())
def test_pkg4_filter_is_idempotent(events: list, f: EventFilter) -> None:
    once = apply(f, events)
    twice = apply(f, once)
    assert [e.event_id for e in once] == [e.event_id for e in twice]
