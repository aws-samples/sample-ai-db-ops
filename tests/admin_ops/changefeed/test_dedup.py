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

"""Property P10 (R4.6) — Change_Feed dedup idempotence.

For every list L and every e in L: dedupe(L + [e]) == dedupe(L).
Reprocessing an already-seen event never grows the feed.

Also exercises the store: a duplicate put_event returns False and the feed
does not grow.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st

from src.admin_ops.changefeed import store as store_mod
from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
from src.admin_ops.changefeed.store import ChangeFeedFilter, dedupe, put_event, query
from tests.admin_ops.changefeed._inmemory import InMemoryChangeFeedBackend

_SOURCES = ["git", "cloudtrail", "agent", "database"]
_ENGINES = [None, "postgresql", "mysql", "oracle", "dynamodb"]
_SEVERITIES = ["low", "medium", "high", "critical"]
_TIMESTAMPS = st.datetimes(
    min_value=datetime(2010, 1, 1),
    max_value=datetime(2030, 1, 1),
    timezones=st.just(timezone.utc),
)


@st.composite
def change_events(draw: st.DrawFn) -> ChangeEvent:
    source = draw(st.sampled_from(_SOURCES))
    # Draw actor / resource_id from a small pool so collisions (and thus
    # equal deterministic ids) actually occur.
    actor = draw(st.sampled_from(["alice", "bob", "carol", "agent-x"]))
    resource_id = draw(st.sampled_from(["db-orders", "db-users", "config.yaml"]))
    ts = draw(_TIMESTAMPS)
    return ChangeEvent(
        event_id=make_event_id(source, actor, ts, resource_id),
        source=source,
        actor=actor,
        timestamp=ts,
        engine=draw(st.sampled_from(_ENGINES)),
        resource_id=resource_id,
        severity=draw(st.sampled_from(_SEVERITIES)),
        summary=draw(st.text(min_size=1, max_size=80)),
        details_url="https://example.com/x",
        raw_payload_ref="ref",
    )


@settings(deadline=None, max_examples=200)
@given(events=st.lists(change_events(), min_size=1, max_size=20), index=st.integers())
def test_p10_dedup_idempotent(events: list[ChangeEvent], index: int) -> None:
    e = events[index % len(events)]
    assert dedupe(events + [e]) == dedupe(events)


@settings(deadline=None, max_examples=100)
@given(events=st.lists(change_events(), max_size=20))
def test_dedupe_preserves_first_occurrence_order(events: list[ChangeEvent]) -> None:
    result = dedupe(events)
    ids = [e.event_id for e in result]
    assert len(ids) == len(set(ids))  # no duplicates
    # First-occurrence order preserved.
    seen: list[str] = []
    for e in events:
        if e.event_id not in seen:
            seen.append(e.event_id)
    assert ids == seen


def test_put_event_duplicate_returns_false_and_does_not_grow() -> None:
    store_mod.set_backend_for_testing(InMemoryChangeFeedBackend())
    ts = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    event = ChangeEvent(
        event_id=make_event_id("agent", "alice", ts, "db-orders"),
        source="agent",
        actor="alice",
        timestamp=ts,
        engine="postgresql",
        resource_id="db-orders",
        severity="high",
        summary="did a thing",
        details_url="https://example.com/x",
        raw_payload_ref="ref",
    )
    assert put_event(event) is True
    assert put_event(event) is False  # idempotent

    result = query(ChangeFeedFilter(), page=1, page_size=50)
    assert result["total_pages"] == 1
    assert len(result["events"]) == 1


def test_put_event_distinct_ids_grow_feed() -> None:
    store_mod.set_backend_for_testing(InMemoryChangeFeedBackend())
    ts = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    for actor in ("alice", "bob"):
        event = ChangeEvent(
            event_id=make_event_id("agent", actor, ts, "db-orders"),
            source="agent",
            actor=actor,
            timestamp=ts,
            engine="postgresql",
            resource_id="db-orders",
            severity="high",
            summary="did a thing",
            details_url="https://example.com/x",
            raw_payload_ref="ref",
        )
        assert put_event(event) is True
    result = query(ChangeFeedFilter(), page=1, page_size=50)
    assert len(result["events"]) == 2
