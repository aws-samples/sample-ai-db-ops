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

"""Property P9 (R4.8) — Change_Event serializer round-trip.

For every well-formed ChangeEvent e: parse(print_event(e)) == e.

The strategy covers all three sources (git, cloudtrail, agent) and the full
range of field constraints.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st

from src.admin_ops.changefeed.change_event import (
    ChangeEvent,
    make_event_id,
    parse,
    print_event,
)

_SOURCES = st.sampled_from(["git", "cloudtrail", "agent", "database"])
_ENGINES = st.one_of(
    st.none(),
    st.sampled_from(["postgresql", "mysql", "oracle", "dynamodb"]),
)
_SEVERITIES = st.sampled_from(["low", "medium", "high", "critical"])
_ACTOR = st.text(min_size=1, max_size=128)
_RESOURCE_ID = st.text(min_size=1, max_size=256)
_SUMMARY = st.text(min_size=1, max_size=512)
_DETAILS_URL = st.text(min_size=1, max_size=2048)
_RAW_REF = st.text(min_size=1, max_size=512)
_TIMESTAMPS = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.just(timezone.utc),
)


@settings(deadline=None, max_examples=200)
@given(
    source=_SOURCES,
    actor=_ACTOR,
    timestamp=_TIMESTAMPS,
    engine=_ENGINES,
    resource_id=_RESOURCE_ID,
    severity=_SEVERITIES,
    summary=_SUMMARY,
    details_url=_DETAILS_URL,
    raw_payload_ref=_RAW_REF,
)
def test_p9_round_trip(
    source: str,
    actor: str,
    timestamp: datetime,
    engine: str | None,
    resource_id: str,
    severity: str,
    summary: str,
    details_url: str,
    raw_payload_ref: str,
) -> None:
    event = ChangeEvent(
        event_id=make_event_id(source, actor, timestamp, resource_id),
        source=source,
        actor=actor,
        timestamp=timestamp,
        engine=engine,
        resource_id=resource_id,
        severity=severity,
        summary=summary,
        details_url=details_url,
        raw_payload_ref=raw_payload_ref,
    )
    assert parse(print_event(event)) == event


def test_p9_round_trip_accepts_dict_and_string() -> None:
    ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    event = ChangeEvent(
        event_id=make_event_id("git", "alice", ts, "src/registry/templates/pg.yaml"),
        source="git",
        actor="alice",
        timestamp=ts,
        engine="postgresql",
        resource_id="src/registry/templates/pg.yaml",
        severity="low",
        summary="touched a template",
        details_url="https://example.com/commit/abc",
        raw_payload_ref="git:abc",
    )
    rendered = print_event(event)
    assert parse(rendered) == event
    assert parse(event.model_dump(mode="json")) == event


def test_print_event_is_canonical_sorted_keys() -> None:
    ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    event = ChangeEvent(
        event_id="abc123",
        source="agent",
        actor="agent-x",
        timestamp=ts,
        engine=None,
        resource_id="config.yaml",
        severity="critical",
        summary="s",
        details_url="https://example.com",
        raw_payload_ref="ref",
    )
    out = print_event(event)
    # Keys appear in sorted order; serialization is stable across calls.
    assert out == print_event(event)
    assert out.index('"actor"') < out.index('"event_id"') < out.index('"source"')
