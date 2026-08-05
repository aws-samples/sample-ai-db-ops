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

"""In-process dev end-to-end test for the no-Neptune demo path (R2.1, R4.3, R6.1, R7.4).

With ``ADMIN_DEV_BYPASS=1`` and ``gating_state=approved``, seed the dev backend
from a controlled change-feed JSON, then drive the full read surface — gating,
``query.connected``, ``query.unticketed_changes``, and the timeline filter
algebra — entirely in-process against the in-memory backend (no AWS). Asserts
connected traversal results, unticketed detection, and ordered timeline output.

This exercises the same wiring the UI uses: the dev store builds the graph from
the change-feed JSON via the pure mapper + seeded ticket linkage, and
``store._get_backend()`` selects it when ``ADMIN_DEV_BYPASS=1``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.admin_ops.changefeed.change_event import make_event_id
from src.admin_ops.config import require as require_module
from src.admin_ops.kg import gate, store
from src.admin_ops.kg.filters import EventFilter, apply, order_timeline
from src.admin_ops.kg.model import make_node_id
from src.admin_ops.kg.query import (
    TraversalParams,
    connected,
    database_ddl_activity,
    unticketed_changes,
)


def _ts(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def _event(*, actor: str, db: str, table: str, verb: str, severity: str, days_ago: int) -> dict:
    ts = _ts(days_ago)
    obj = f"TABLE {table}"
    resource_id = f"pg_ddl:{db}:{obj}"
    return {
        "event_id": make_event_id("database", actor, ts, resource_id),
        "source": "database",
        "actor": actor,
        "timestamp": ts.isoformat(),
        "engine": "postgresql",
        "resource_id": resource_id,
        "severity": severity,
        "summary": f"{verb} on {obj} ({db}): {verb} {obj} ...",
        "details_url": f"cloudwatch:postgresql:{db}",
        "raw_payload_ref": "pgddl:stream:1",
    }


@pytest.fixture
def dev_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up ADMIN_DEV_BYPASS=1, gating=approved, and a seeded change-feed JSON."""
    # 1. config.yaml with approved gating + a placeholder account alias.
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "account": {"alias": "dbops-user"},
                "knowledge_graph": {"gating_state": "approved"},
            }
        )
    )
    monkeypatch.setenv("ADMIN_OPS_CONFIG_PATH", str(cfg))
    require_module._reset_cache()

    # 2. dev change-feed JSON the kg dev store reads via JsonFileChangeFeedBackend.
    feed_file = tmp_path / "dev_changefeed.json"
    events = [
        # Two ticketed DDL events on shop.orders (linked by seeded pattern -> CHG-1042).
        _event(actor="appuser@appdb", db="database-test", table="shop.orders",
               verb="ALTER", severity="high", days_ago=2),
        _event(actor="appuser@appdb", db="database-test", table="shop.orders",
               verb="CREATE", severity="medium", days_ago=5),
        # One UNTICKETED high-severity DDL on an unlinked table.
        _event(actor="dbops@postgres", db="orders-db", table="billing.invoices",
               verb="DROP", severity="critical", days_ago=1),
    ]
    feed_file.write_text(json.dumps(events))
    monkeypatch.setenv("CHANGEFEED_DEV_STATE_FILE", str(feed_file))
    monkeypatch.setenv("ADMIN_DEV_BYPASS", "1")

    # 3. Reset the kg backend so _get_backend rebuilds the seeded dev backend.
    store.set_backend_for_testing(None)
    yield {"events": events}
    store.set_backend_for_testing(None)
    require_module._reset_cache()


def test_gate_is_approved_in_dev(dev_env) -> None:
    assert gate.gating_state() == "approved"
    gate.require_approved()  # does not raise


def test_connected_traversal_from_database(dev_env) -> None:
    db_node = make_node_id("Database", "database-test")
    result = connected(TraversalParams(focus_node_id=db_node, hops=3, days=365))
    node_ids = {n.node_id for n in result.nodes}
    # The database and its table are reachable.
    assert db_node in node_ids
    assert make_node_id("Table", "database-test:shop.orders") in node_ids
    # The shop.orders DDL ChangeEvents are reachable within 3 hops.
    ce_types = {n.type for n in result.nodes}
    assert "ChangeEvent" in ce_types


def test_database_ddl_activity_links_tickets(dev_env) -> None:
    db_node = make_node_id("Database", "database-test")
    result = database_ddl_activity(db_node, days=365)
    types = {n.type for n in result.nodes}
    # The shop.orders events are DDL and link to CHG-1042 via seeded linkage.
    assert "ChangeEvent" in types
    assert "Ticket" in types
    ticket_ids = {n.label for n in result.nodes if n.type == "Ticket"}
    assert "CHG-1042" in ticket_ids


def test_unticketed_detection_finds_the_unlinked_drop(dev_env) -> None:
    result = unticketed_changes(days=365)
    assert result.complete is True
    summaries = {n.label for n in result.events}
    # The critical DROP on billing.invoices has no seeded ticket linkage.
    assert any("billing.invoices" in s for s in summaries)
    # The shop.orders events ARE ticketed, so they must not appear.
    assert not any("shop.orders" in s for s in summaries)


def test_timeline_filter_and_order_end_to_end(dev_env) -> None:
    # Pull the raw events back through the change-feed backend the dev store reads.
    from src.admin_ops.changefeed._dev_store import JsonFileChangeFeedBackend

    feed = JsonFileChangeFeedBackend()
    events = feed.all_events()

    # DDL-only + high/critical, reverse-chronological page.
    filtered = apply(EventFilter(ddl_only=True, severities=["high", "critical"]), events)
    page = order_timeline(filtered, page=1)
    rows = page["events"]
    assert len(rows) == 2  # the ALTER (high) + the DROP (critical)
    # Reverse-chronological: the most recent (DROP, 1 day ago) comes first.
    assert rows[0].timestamp >= rows[1].timestamp
