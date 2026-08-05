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

"""Tier-1-only bundle fetcher contract tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

import pytest

from src.admin_ops.reports import fetcher as f


@pytest.fixture(autouse=True)
def _isolate():
    calls: list[tuple[str, str, Any]] = []

    def stub_invoker(engine: str, tool: str, args: Mapping[str, Any] | None):
        calls.append((engine, tool, args))
        if tool == "get_slow_queries" and engine == "postgresql":
            return {
                "queries": [
                    {
                        "queryid": "abc123",
                        "query_preview": "SELECT * FROM t WHERE k = ?",
                        "calls": 9,
                        "mean_ms": 12.5,
                        "total_ms": 112.5,
                    }
                ]
            }
        if tool == "detect_blocking_chains":
            return {"blocking_chains": []}
        if tool == "get_index_usage":
            return {
                "unused_indexes": [
                    {
                        "schemaname": "public",
                        "relname": "users",
                        "indexrelname": "idx_users_email",
                        "size_mb": 4.2,
                        "idx_scan": 0,
                    }
                ]
            }
        if tool == "get_vacuum_status":
            return {
                "vacuum_status": [
                    {"relname": "shop.orders", "n_dead_tup": 12345}
                ]
            }
        return {}

    f.set_agent_invoker_for_testing(stub_invoker)
    yield calls
    f.set_agent_invoker_for_testing(None)


def test_postgres_bundle_shape(_isolate):
    b = f.fetch_bundle(
        db_identifier="db-1",
        engine="postgresql",
        until=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    # Sections present and shaped correctly.
    assert b["top_slow_queries"][0]["query_id"] == "abc123"
    assert b["top_slow_queries"][0]["mean_time_sec"] == pytest.approx(0.0125)
    assert b["unused_indexes"][0]["schema"] == "public"
    assert b["unused_indexes"][0]["table"] == "users"
    assert b["vacuum_undo_status"][0]["metric"] == "n_dead_tup"
    assert b["blocking_incidents"] == []
    # Tier 3 ops empty when no audit log fetcher is configured.
    assert b["tier3_ops"] == []
    # Summary present.
    assert b["summary"]["engine"] == "postgresql"


def test_failed_section_returns_empty_list(_isolate):
    def boom(engine, tool, args):
        if tool == "get_slow_queries":
            raise RuntimeError("simulated tool failure")
        return {"unused_indexes": [], "blocking_chains": [], "vacuum_status": []}

    f.set_agent_invoker_for_testing(boom)
    b = f.fetch_bundle(db_identifier="db-1", engine="postgresql")
    assert b["top_slow_queries"] == []
    # Other sections still populated.
    assert b["unused_indexes"] == []


def test_tier3_ops_uses_fetcher_when_configured():
    def fake(db, since, until):
        return [
            {"timestamp": "2026-05-21T10:00:00Z", "actor": "alice", "tool": "x", "outcome": "ok", "summary": "y"}
        ]

    f.set_audit_log_fetcher_for_testing(fake)
    try:

        def stub_invoker(engine, tool, args):
            return {}

        f.set_agent_invoker_for_testing(stub_invoker)
        b = f.fetch_bundle(db_identifier="db-1", engine="postgresql")
        assert b["tier3_ops"][0]["actor"] == "alice"
    finally:
        f.set_audit_log_fetcher_for_testing(None)
        f.set_agent_invoker_for_testing(None)


def test_unsupported_engine_returns_skeleton(_isolate):
    b = f.fetch_bundle(db_identifier="db", engine="redshift")
    assert b["top_slow_queries"] == []
    assert b["unused_indexes"] == []
    assert b["summary"]["engine"] == "redshift"
