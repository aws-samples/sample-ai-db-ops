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

"""Shared Hypothesis strategies + helpers for kg tests (no AWS).

Builds valid ``ChangeEvent``s across all four sources. The ``database`` source
uses realistic ``pg_ddl:{db}:{object}`` ``resource_id`` shapes and verb-led
``summary`` strings so ``parse_resource`` / ``ddl_kind_of`` are exercised.

Also provides a tiny duck-typed ``StubLinkage`` standing in for the Phase-4
``TicketLinkage`` (``by_event_id`` + ``by_resource_pattern``) so the pure mapper
can resolve tickets without importing ticket code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from hypothesis import strategies as st

from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id

ACCOUNT_KEY = "appuser@appdb"

_DDL_VERBS = ["ALTER", "TRUNCATE", "CREATE", "DROP"]
_NON_DDL_DB_VERBS = ["COMMENT", "GRANT", "REVOKE"]  # database source, not a DDL kind
_DBS = ["database-test", "shop-db", "orders-db"]
_TABLES = ["shop.orders", "shop.order_items", "public.users"]
_ACTORS = ["appuser@appdb", "dbops@postgres", "alice", "bob", "agent-x"]
_SEVERITIES = ["low", "medium", "high", "critical"]

_TIMESTAMPS = st.datetimes(
    min_value=datetime(2015, 1, 1),
    max_value=datetime(2030, 1, 1),
    timezones=st.just(timezone.utc),
)


@dataclass(frozen=True)
class StubLinkage:
    """Duck-typed stand-in for the Phase-4 TicketLinkage."""

    by_event_id: dict[str, str] = field(default_factory=dict)
    by_resource_pattern: list[tuple[str, str]] = field(default_factory=list)


@st.composite
def database_ddl_events(draw: st.DrawFn) -> ChangeEvent:
    """A ``database``-source DDL event with a table (pg_ddl-shaped)."""
    verb = draw(st.sampled_from(_DDL_VERBS))
    db = draw(st.sampled_from(_DBS))
    table = draw(st.sampled_from(_TABLES))
    actor = draw(st.sampled_from(_ACTORS))
    ts = draw(_TIMESTAMPS)
    obj = f"TABLE {table}"
    resource_id = f"pg_ddl:{db}:{obj}"
    summary = f"{verb} on {obj} ({db}): {verb} {obj} ..."[:512]
    return ChangeEvent(
        event_id=make_event_id("database", actor, ts, resource_id),
        source="database",
        actor=actor,
        timestamp=ts,
        engine="postgresql",
        resource_id=resource_id,
        severity=draw(st.sampled_from(_SEVERITIES)),
        summary=summary,
        details_url=f"cloudwatch:postgresql:{db}",
        raw_payload_ref="pgddl:stream:1",
    )


@st.composite
def database_nontable_events(draw: st.DrawFn) -> ChangeEvent:
    """A ``database``-source event whose object is not a TABLE (db only)."""
    verb = draw(st.sampled_from(_DDL_VERBS + _NON_DDL_DB_VERBS))
    db = draw(st.sampled_from(_DBS))
    actor = draw(st.sampled_from(_ACTORS))
    ts = draw(_TIMESTAMPS)
    obj = f"INDEX idx_{draw(st.integers(min_value=0, max_value=9))}"
    resource_id = f"pg_ddl:{db}:{obj}"
    summary = f"{verb} on {obj} ({db}): {verb} {obj} ..."[:512]
    return ChangeEvent(
        event_id=make_event_id("database", actor, ts, resource_id),
        source="database",
        actor=actor,
        timestamp=ts,
        engine="postgresql",
        resource_id=resource_id,
        severity=draw(st.sampled_from(_SEVERITIES)),
        summary=summary,
        details_url=f"cloudwatch:postgresql:{db}",
        raw_payload_ref="pgddl:stream:1",
    )


@st.composite
def non_database_events(draw: st.DrawFn) -> ChangeEvent:
    """A git / cloudtrail / agent event (no parseable table or db)."""
    source = draw(st.sampled_from(["git", "cloudtrail", "agent"]))
    actor = draw(st.sampled_from(_ACTORS))
    ts = draw(_TIMESTAMPS)
    resource_id = draw(
        st.sampled_from(
            [
                "src/registry/templates/pg.yaml",
                "config.yaml",
                "ListBuckets",
                "agent:run:1",
            ]
        )
    )
    return ChangeEvent(
        event_id=make_event_id(source, actor, ts, resource_id),
        source=source,
        actor=actor,
        timestamp=ts,
        engine=draw(st.sampled_from([None, "postgresql", "mysql"])),
        resource_id=resource_id,
        severity=draw(st.sampled_from(_SEVERITIES)),
        summary=draw(st.text(min_size=1, max_size=80)),
        details_url="https://example.com/x",
        raw_payload_ref="ref",
    )


def change_events() -> st.SearchStrategy[ChangeEvent]:
    """Any ChangeEvent across all four sources, DDL + non-DDL variants."""
    return st.one_of(
        database_ddl_events(),
        database_nontable_events(),
        non_database_events(),
    )
