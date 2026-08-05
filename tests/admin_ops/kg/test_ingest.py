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

"""Unit tests for the mapper helpers (R2.4, R8.1).

* parse_resource on pg_ddl-shaped resource_ids
* ddl_kind_of on each verb
* non-DDL / non-table events produce only ChangeEvent + Principal (+ MODIFIED_BY)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
from src.admin_ops.kg.ingest import ddl_kind_of, map_change_event, parse_resource

ACCOUNT_KEY = "appuser@appdb"
_TS = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _db_event(resource_id: str, summary: str, severity: str = "high") -> ChangeEvent:
    return ChangeEvent(
        event_id=make_event_id("database", "appuser@appdb", _TS, resource_id),
        source="database",
        actor="appuser@appdb",
        timestamp=_TS,
        engine="postgresql",
        resource_id=resource_id,
        severity=severity,
        summary=summary,
        details_url="cloudwatch:postgresql:database-test",
        raw_payload_ref="pgddl:stream:1",
    )


def _other_event(source: str, resource_id: str) -> ChangeEvent:
    return ChangeEvent(
        event_id=make_event_id(source, "alice", _TS, resource_id),
        source=source,
        actor="alice",
        timestamp=_TS,
        engine=None,
        resource_id=resource_id,
        severity="low",
        summary="did a thing",
        details_url="https://example.com/x",
        raw_payload_ref="ref",
    )


# --- parse_resource ----------------------------------------------------------


def test_parse_resource_extracts_db_and_table() -> None:
    e = _db_event(
        "pg_ddl:database-test:TABLE shop.orders",
        "ALTER on TABLE shop.orders (database-test): ALTER ...",
    )
    assert parse_resource(e) == ("database-test", "shop.orders")


def test_parse_resource_db_only_when_object_not_table() -> None:
    e = _db_event(
        "pg_ddl:database-test:INDEX idx_x",
        "CREATE on INDEX idx_x (database-test): CREATE ...",
    )
    assert parse_resource(e) == ("database-test", None)


def test_parse_resource_handles_schema_qualified_table() -> None:
    e = _db_event(
        "pg_ddl:orders-db:TABLE public.users",
        "DROP on TABLE public.users (orders-db): DROP ...",
    )
    assert parse_resource(e) == ("orders-db", "public.users")


@pytest.mark.parametrize("source", ["git", "cloudtrail", "agent"])
def test_parse_resource_non_database_returns_none_none(source: str) -> None:
    e = _other_event(source, "src/registry/templates/pg.yaml")
    assert parse_resource(e) == (None, None)


# --- ddl_kind_of -------------------------------------------------------------


@pytest.mark.parametrize("verb", ["ALTER", "TRUNCATE", "CREATE", "DROP"])
def test_ddl_kind_of_recognizes_each_ddl_verb(verb: str) -> None:
    e = _db_event(
        f"pg_ddl:database-test:TABLE shop.orders",
        f"{verb} on TABLE shop.orders (database-test): {verb} ...",
    )
    assert ddl_kind_of(e) == verb


@pytest.mark.parametrize("verb", ["GRANT", "REVOKE", "COMMENT"])
def test_ddl_kind_of_non_ddl_database_verbs_return_none(verb: str) -> None:
    # database source but not one of the four DDL kinds.
    e = _db_event(
        f"pg_ddl:database-test:TABLE shop.orders",
        f"{verb} on TABLE shop.orders (database-test): {verb} ...",
    )
    assert ddl_kind_of(e) is None


@pytest.mark.parametrize("source", ["git", "cloudtrail", "agent"])
def test_ddl_kind_of_non_database_source_returns_none(source: str) -> None:
    e = _other_event(source, "config.yaml")
    assert ddl_kind_of(e) is None


def test_ddl_kind_recovered_from_resource_when_summary_lacks_verb() -> None:
    # summary does not start with a DDL verb; resource object does.
    e = _db_event(
        "pg_ddl:database-test:DROP shop.tmp",
        "schema change recorded",
    )
    assert ddl_kind_of(e) == "DROP"


# --- non-DDL / non-table mapping ---------------------------------------------


@pytest.mark.parametrize("source", ["git", "cloudtrail", "agent"])
def test_non_database_event_yields_only_changeevent_and_principal(source: str) -> None:
    e = _other_event(source, "config.yaml")
    mutation = map_change_event(e, account_key=ACCOUNT_KEY)
    types = sorted(n.type for n in mutation.nodes)
    assert types == ["ChangeEvent", "Principal"]
    edge_types = [edge.edge_type for edge in mutation.edges]
    assert edge_types == ["MODIFIED_BY"]


def test_database_event_without_table_has_db_and_account_but_no_table() -> None:
    e = _db_event(
        "pg_ddl:database-test:INDEX idx_x",
        "CREATE on INDEX idx_x (database-test): CREATE ...",
    )
    mutation = map_change_event(e, account_key=ACCOUNT_KEY)
    types = sorted(n.type for n in mutation.nodes)
    assert types == ["Account", "ChangeEvent", "Database", "Principal"]
    edge_types = sorted(edge.edge_type for edge in mutation.edges)
    assert edge_types == ["MODIFIED_BY", "OWNS"]


def test_database_event_with_table_has_full_chain() -> None:
    e = _db_event(
        "pg_ddl:database-test:TABLE shop.orders",
        "ALTER on TABLE shop.orders (database-test): ALTER ...",
    )
    mutation = map_change_event(e, account_key=ACCOUNT_KEY)
    types = sorted(n.type for n in mutation.nodes)
    assert types == ["Account", "ChangeEvent", "Database", "Principal", "Table"]
    edge_types = sorted(edge.edge_type for edge in mutation.edges)
    assert edge_types == ["BELONGS_TO", "MODIFIED_BY", "OWNS", "RUNS_AGAINST"]
