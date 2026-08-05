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

"""Tests for the PostgreSQL DDL ingester (`database` source, R4.4)."""

from __future__ import annotations

import pytest

from src.admin_ops.changefeed import store as store_mod
from src.admin_ops.changefeed.ingest import pg_ddl
from src.admin_ops.changefeed.store import ChangeFeedFilter, query
from tests.admin_ops.changefeed._inmemory import InMemoryChangeFeedBackend


def _log(stmt: str, user: str = "appuser", db: str = "appdb") -> str:
    return (
        f"2026-06-02 15:30:01 UTC:10.0.5.1(54321):{user}@{db}:[1234]:LOG:  "
        f"statement: {stmt}"
    )


@pytest.mark.parametrize(
    "stmt,verb,severity",
    [
        ("ALTER TABLE shop.orders ADD COLUMN note text;", "ALTER", "high"),
        ("TRUNCATE TABLE shop.order_items;", "TRUNCATE", "high"),
        ("DROP TABLE IF EXISTS shop.tmp;", "DROP", "high"),
        ("CREATE INDEX idx_x ON shop.orders(customer_id);", "CREATE", "medium"),
        ("GRANT SELECT ON shop.orders TO reporting;", "GRANT", "high"),
        ("COMMENT ON TABLE shop.orders IS 'x';", "COMMENT", "low"),
    ],
)
def test_ddl_verbs_classified(stmt, verb, severity):
    r = pg_ddl.parse_pg_log_message(_log(stmt))
    assert r is not None
    assert r["verb"] == verb
    assert r["severity"] == severity


@pytest.mark.parametrize(
    "stmt",
    [
        "SELECT * FROM shop.orders LIMIT 10;",
        "INSERT INTO shop.orders VALUES (1);",
        "UPDATE shop.orders SET note='x';",
        "SET work_mem = 64;",
        "BEGIN;",
    ],
)
def test_non_ddl_skipped(stmt):
    assert pg_ddl.parse_pg_log_message(_log(stmt)) is None


def test_non_statement_line_skipped():
    assert pg_ddl.parse_pg_log_message("connection authorized: user=foo") is None
    assert pg_ddl.parse_pg_log_message("") is None


def test_actor_extracted_from_user_db():
    r = pg_ddl.parse_pg_log_message(_log("ALTER TABLE t ADD COLUMN c int;", user="dba", db="prod"))
    assert r is not None
    assert r["actor"] == "dba@prod"


def test_handler_writes_events_and_skips_noise():
    store_mod.set_backend_for_testing(InMemoryChangeFeedBackend())
    payload = {
        "logGroup": "/aws/rds/cluster/database-test/postgresql",
        "logStream": "database-test-instance-1",
        "logEvents": [
            {"timestamp": 1780000001000, "message": _log("ALTER TABLE shop.orders ADD COLUMN n text;")},
            {"timestamp": 1780000002000, "message": _log("TRUNCATE TABLE shop.order_items;", user="dbops", db="postgres")},
            {"timestamp": 1780000003000, "message": _log("SELECT 1;")},
            {"timestamp": 1780000004000, "message": "garbage record"},
        ],
    }
    res = pg_ddl.handle_cloudwatch_logs_event(payload)
    assert res["scanned"] == 4
    assert res["events_written"] == 2
    assert res["db_identifier"] == "database-test"

    out = query(ChangeFeedFilter(sources=["database"]), page=1, page_size=10)
    assert len(out["events"]) == 2
    assert all(e.source == "database" and e.engine == "postgresql" for e in out["events"])


def test_handler_idempotent_on_replay():
    store_mod.set_backend_for_testing(InMemoryChangeFeedBackend())
    payload = {
        "logGroup": "/aws/rds/cluster/database-test/postgresql",
        "logStream": "s1",
        "logEvents": [
            {"timestamp": 1780000001000, "message": _log("ALTER TABLE shop.orders ADD COLUMN n text;")},
        ],
    }
    first = pg_ddl.handle_cloudwatch_logs_event(payload)
    second = pg_ddl.handle_cloudwatch_logs_event(payload)
    assert first["events_written"] == 1
    assert second["events_written"] == 0  # deterministic id -> dedup (R4.6)
    out = query(ChangeFeedFilter(sources=["database"]), page=1, page_size=10)
    assert len(out["events"]) == 1


def test_db_identifier_from_log_group():
    assert pg_ddl._db_from_log_group("/aws/rds/cluster/my-cluster/postgresql") == "my-cluster"
    assert pg_ddl._db_from_log_group("weird") == "database-test"
