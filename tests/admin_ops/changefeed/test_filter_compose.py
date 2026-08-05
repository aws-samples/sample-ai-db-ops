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

"""Property P11 (R4.11) — Change_Feed filter compositionality.

For every list L and every pair of filters f1, f2:
    apply_filter(f2, apply_filter(f1, L)) == apply_filter(f1, apply_filter(f2, L))

Filter order does not change the result (confluence). Plus concrete unit
tests proving AND-across / OR-within semantics, the inclusive time range,
reverse-chronological pagination, and the >10-values-per-category guard.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from hypothesis import given, settings, strategies as st

from src.admin_ops.changefeed import store as store_mod
from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
from src.admin_ops.changefeed.store import (
    ChangeFeedFilter,
    apply_filter,
    put_event,
    query,
)
from tests.admin_ops.changefeed._inmemory import InMemoryChangeFeedBackend

_SOURCES = ["git", "cloudtrail", "agent", "database"]
_ENGINES = [None, "postgresql", "mysql", "oracle", "dynamodb"]
_NON_NULL_ENGINES = ["postgresql", "mysql", "oracle", "dynamodb"]
_SEVERITIES = ["low", "medium", "high", "critical"]
_TIMESTAMPS = st.datetimes(
    min_value=datetime(2015, 1, 1),
    max_value=datetime(2025, 1, 1),
    timezones=st.just(timezone.utc),
)


@st.composite
def change_events(draw: st.DrawFn) -> ChangeEvent:
    source = draw(st.sampled_from(_SOURCES))
    actor = draw(st.sampled_from(["alice", "bob", "carol"]))
    resource_id = draw(st.sampled_from(["db-orders", "db-users"]))
    ts = draw(_TIMESTAMPS)
    return ChangeEvent(
        event_id=make_event_id(source, actor, ts, resource_id) + draw(
            st.sampled_from(["", "a", "b"])
        ),
        source=source,
        actor=actor,
        timestamp=ts,
        engine=draw(st.sampled_from(_ENGINES)),
        resource_id=resource_id,
        severity=draw(st.sampled_from(_SEVERITIES)),
        summary="s",
        details_url="https://example.com/x",
        raw_payload_ref="ref",
    )


def _subset(values: list, draw: st.DrawFn):
    chosen = draw(st.lists(st.sampled_from(values), max_size=min(10, len(values)), unique=True))
    return chosen or None


@st.composite
def filters(draw: st.DrawFn) -> ChangeFeedFilter:
    sources = draw(st.one_of(st.none(), st.just(_subset(_SOURCES, draw))))
    engines = draw(st.one_of(st.none(), st.just(_subset(_NON_NULL_ENGINES, draw))))
    severities = draw(st.one_of(st.none(), st.just(_subset(_SEVERITIES, draw))))
    t1 = draw(st.one_of(st.none(), _TIMESTAMPS))
    t2 = draw(st.one_of(st.none(), _TIMESTAMPS))
    return ChangeFeedFilter(
        sources=sources,
        engines=engines,
        severities=severities,
        time_from=t1,
        time_to=t2,
    )


@settings(deadline=None, max_examples=200)
@given(
    events=st.lists(change_events(), max_size=25),
    f1=filters(),
    f2=filters(),
)
def test_p11_filter_composition_confluent(
    events: list[ChangeEvent],
    f1: ChangeFeedFilter,
    f2: ChangeFeedFilter,
) -> None:
    left = apply_filter(f2, apply_filter(f1, events))
    right = apply_filter(f1, apply_filter(f2, events))
    assert left == right


# ─── Concrete semantics ─────────────────────────────────────────────────────


def _mk(source: str, engine, severity: str, day: int) -> ChangeEvent:
    ts = datetime(2024, 1, day, 12, 0, 0, tzinfo=timezone.utc)
    return ChangeEvent(
        event_id=make_event_id(source, "alice", ts, f"r{day}") + severity[0],
        source=source,
        actor="alice",
        timestamp=ts,
        engine=engine,
        resource_id=f"r{day}",
        severity=severity,
        summary="s",
        details_url="https://example.com/x",
        raw_payload_ref="ref",
    )


def test_or_within_category() -> None:
    events = [
        _mk("git", "postgresql", "low", 1),
        _mk("cloudtrail", "postgresql", "low", 2),
        _mk("agent", "postgresql", "low", 3),
    ]
    f = ChangeFeedFilter(sources=["git", "agent"])
    out = apply_filter(f, events)
    assert {e.source for e in out} == {"git", "agent"}
    assert len(out) == 2


def test_and_across_categories() -> None:
    events = [
        _mk("git", "postgresql", "high", 1),  # matches both
        _mk("git", "mysql", "high", 2),  # wrong engine
        _mk("agent", "postgresql", "high", 3),  # wrong source
    ]
    f = ChangeFeedFilter(sources=["git"], engines=["postgresql"], severities=["high"])
    out = apply_filter(f, events)
    assert len(out) == 1
    assert out[0].timestamp.day == 1


def test_inclusive_time_range() -> None:
    events = [_mk("git", "postgresql", "low", d) for d in (1, 2, 3, 4)]
    f = ChangeFeedFilter(
        time_from=datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
        time_to=datetime(2024, 1, 3, 12, 0, 0, tzinfo=timezone.utc),
    )
    out = apply_filter(f, events)
    assert {e.timestamp.day for e in out} == {2, 3}  # both endpoints inclusive


def test_empty_filter_matches_everything() -> None:
    events = [_mk("git", "postgresql", "low", d) for d in (1, 2, 3)]
    assert apply_filter(ChangeFeedFilter(), events) == events


def test_engine_filter_excludes_null_engine() -> None:
    events = [_mk("git", None, "low", 1), _mk("git", "postgresql", "low", 2)]
    out = apply_filter(ChangeFeedFilter(engines=["postgresql"]), events)
    assert len(out) == 1
    assert out[0].engine == "postgresql"


@pytest.mark.parametrize("field", ["sources", "engines", "severities"])
def test_more_than_ten_values_raises(field: str) -> None:
    # 11 values (with repeats to reach length) must raise.
    pool = {
        "sources": _SOURCES,
        "engines": _NON_NULL_ENGINES,
        "severities": _SEVERITIES,
    }[field]
    too_many = [pool[i % len(pool)] for i in range(11)]
    with pytest.raises(ValueError):
        ChangeFeedFilter(**{field: too_many})


def test_exactly_ten_values_ok() -> None:
    ten = [_SEVERITIES[i % len(_SEVERITIES)] for i in range(10)]
    f = ChangeFeedFilter(severities=ten)
    assert len(f.severities) == 10


def test_query_reverse_chronological_and_pagination() -> None:
    store_mod.set_backend_for_testing(InMemoryChangeFeedBackend())
    for d in (1, 2, 3, 4, 5):
        put_event(_mk("git", "postgresql", "low", d))

    page1 = query(ChangeFeedFilter(), page=1, page_size=2)
    assert page1["total_pages"] == 3
    assert [e.timestamp.day for e in page1["events"]] == [5, 4]  # newest first

    page2 = query(ChangeFeedFilter(), page=2, page_size=2)
    assert [e.timestamp.day for e in page2["events"]] == [3, 2]

    page3 = query(ChangeFeedFilter(), page=3, page_size=2)
    assert [e.timestamp.day for e in page3["events"]] == [1]


def test_query_applies_filter() -> None:
    store_mod.set_backend_for_testing(InMemoryChangeFeedBackend())
    put_event(_mk("git", "postgresql", "low", 1))
    put_event(_mk("agent", "mysql", "high", 2))
    out = query(ChangeFeedFilter(sources=["agent"]), page=1, page_size=50)
    assert len(out["events"]) == 1
    assert out["events"][0].source == "agent"
