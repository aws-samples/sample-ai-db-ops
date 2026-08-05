#!/usr/bin/env python3
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

"""Generate the bundled demo change-feed dataset for the hosted demo.

Produces a placeholder-only set of ChangeEvents (no AWS account id / ARN /
VPC/subnet/SG id) covering all four sources and a spread of severities. The
DBA Knowledge Graph builds from this in demo mode (ADMIN_DEV_BYPASS=1) when
CHANGEFEED_DEV_STATE_FILE points at the generated file.

Linkage (seeded_tickets.json) matches resource_id regex:
  shop.orders -> CHG-1042, shop.order_items -> CHG-1043, public.users -> CHG-1044.
Tables that match become "ticketed"; high/critical DDL on non-matching tables
(billing.invoices, analytics.events, inventory.skus, shop.audit_demo) surface in
the "unticketed high-severity DDL" panel.

Run:  python3 scripts/gen_demo_changefeed.py
Out:  src/admin_ops/changefeed/data/demo_seed.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id

# Anchor recent so timestamps fall well inside the 365-day query window.
_BASE = datetime(2026, 6, 8, 9, 0, 0, tzinfo=timezone.utc)


def _ago(hours: int) -> datetime:
    return _BASE - timedelta(hours=hours)


def db_ddl(actor, db, table, verb, severity, hours):
    obj = f"TABLE {table}"
    rid = f"pg_ddl:{db}:{obj}"
    ts = _ago(hours)
    return ChangeEvent(
        event_id=make_event_id("database", actor, ts, rid),
        source="database",
        actor=actor,
        timestamp=ts,
        engine="postgresql",
        resource_id=rid,
        severity=severity,
        summary=f"{verb} on {obj} ({db}): {verb} {obj} ...",
        details_url=f"cloudwatch:postgresql:{db}",
        raw_payload_ref="pgddl:stream:1",
    )


def simple(source, actor, rid, severity, summary, hours, engine=None):
    ts = _ago(hours)
    return ChangeEvent(
        event_id=make_event_id(source, actor, ts, rid),
        source=source,
        actor=actor,
        timestamp=ts,
        engine=engine,
        resource_id=rid,
        severity=severity,
        summary=summary[:512],
        details_url=("https://example.com/source" if source == "git" else f"{source}:{rid}"),
        raw_payload_ref=f"{source}:ref",
    )


events = [
    # ── Ticketed DDL on shop.orders (multiple events → rich graph around one table)
    db_ddl("appuser@appdb", "database-test", "shop.orders", "ALTER", "high", 6),
    db_ddl("appuser@appdb", "database-test", "shop.orders", "CREATE", "medium", 30),
    db_ddl("dbadmin@prod", "database-test", "shop.orders", "ALTER", "high", 54),
    # ── Ticketed DDL on other linked tables
    db_ddl("appuser@appdb", "database-test", "shop.order_items", "ALTER", "medium", 18),
    db_ddl("dbadmin@prod", "database-test", "public.users", "TRUNCATE", "high", 42),
    # ── UNTICKETED high/critical DDL (no ticket pattern match) → governance panel
    db_ddl("svc-etl@prod", "database-test", "billing.invoices", "DROP", "critical", 3),
    db_ddl("svc-etl@prod", "orders-db", "analytics.events", "ALTER", "high", 12),
    db_ddl("ci-bot", "database-test", "inventory.skus", "TRUNCATE", "critical", 27),
    db_ddl("appuser@appdb", "database-test", "shop.audit_demo", "ALTER", "high", 1),
    # ── Low/medium DDL (not flagged as unticketed since not high/critical)
    db_ddl("ci-bot", "database-test", "staging.tmp_load", "CREATE", "low", 50),
    # ── Git source
    simple("git", "alice", "src/registry/templates/postgresql/slow_query.yaml",
           "medium", "Edit SQL template slow_query.yaml: tighten WHERE clause", 20),
    simple("git", "bob", "migrations/2026_06_add_index.sql",
           "high", "Add migration 2026_06_add_index.sql creating idx on shop.orders", 36),
    # ── CloudTrail source
    simple("cloudtrail", "dbadmin@prod", "ModifyDBCluster:database-test",
           "high", "ModifyDBCluster on database-test: enable log_statement=ddl", 8),
    simple("cloudtrail", "secops@prod", "AuthorizeSecurityGroupIngress",
           "medium", "AuthorizeSecurityGroupIngress: 5432 from app tier", 60),
    # ── Agent (Tier-3 actions)
    simple("agent", "appuser@appdb", "agent:create_index:dbops-aurora-mysql",
           "medium", "Agent created index idx_orders_customer on dbops-aurora-mysql", 16, "mysql"),
    simple("agent", "dbadmin@prod", "agent:kill_session:database-test",
           "low", "Agent killed blocking session pid 48213 on database-test", 22),
]


def main() -> int:
    out = Path(__file__).resolve().parents[1] / "src/admin_ops/changefeed/data/demo_seed.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = [e.model_dump(mode="json") for e in events]
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {len(payload)} events -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
