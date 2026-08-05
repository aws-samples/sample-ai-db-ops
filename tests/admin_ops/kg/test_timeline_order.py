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

"""Property S5 (R6.2) — Timeline reverse-chronological ordering.

For any list of ChangeEvents, each page from ``order_timeline`` is ordered by
``timestamp`` descending with a stable tie-break on ``event_id`` and contains at
most 50 events. Concatenating all pages reproduces the globally sorted order
exactly once per event.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg.filters import PAGE_SIZE, order_timeline
from tests.admin_ops.kg._inmemory import change_events


def _sort_key(e):
    return (e.timestamp, e.event_id)


# Feature: dba-knowledge-graph, Property S5: timeline reverse-chronological order
@settings(deadline=None, max_examples=200)
@given(events=st.lists(change_events(), max_size=40))
def test_s5_each_page_is_reverse_chronological_and_bounded(events: list) -> None:
    # Dedup by event_id (the store dedups) so counts are well-defined.
    by_id = {e.event_id: e for e in events}
    unique = list(by_id.values())

    page = order_timeline(unique, page=1)
    rows = page["events"]
    assert len(rows) <= PAGE_SIZE
    # Descending by (timestamp, event_id).
    keys = [_sort_key(e) for e in rows]
    assert keys == sorted(keys, reverse=True)


# Feature: dba-knowledge-graph, Property S5: pages partition the sorted stream
@settings(deadline=None, max_examples=100)
@given(events=st.lists(change_events(), min_size=1, max_size=40))
def test_s5_pages_concatenate_to_global_order(events: list) -> None:
    by_id = {e.event_id: e for e in events}
    unique = list(by_id.values())
    expected = [e.event_id for e in sorted(unique, key=_sort_key, reverse=True)]

    first = order_timeline(unique, page=1)
    total_pages = first["total_pages"]
    collected: list[str] = []
    for p in range(1, total_pages + 1):
        page = order_timeline(unique, page=p)
        assert len(page["events"]) <= PAGE_SIZE
        collected.extend(e.event_id for e in page["events"])

    assert collected == expected


def test_s5_empty_list_has_zero_pages() -> None:
    page = order_timeline([], page=1)
    assert page["events"] == []
    assert page["total_pages"] == 0
