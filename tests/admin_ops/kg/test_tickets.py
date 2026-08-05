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

"""Unit tests for tickets.py (R7.1-R7.3, R7.6).

* SeededTicketSource loads the placeholder-only bundled dataset.
* A stub TicketSource returning data_origin="integrated" works through the
  same interface (R7.3 — the integration seam).
* TicketLinkage.resolve() applies exact-event-id precedence over pattern.
* get_ticket_source / set_ticket_source_for_testing seam mirrors the store.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
from src.admin_ops.kg.tickets import (
    SeededTicketSource,
    Ticket,
    TicketLinkage,
    TicketSource,
    get_ticket_source,
    set_ticket_source_for_testing,
)

_TS = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

# Patterns flagged by scripts/check_no_resource_ids.py (P-KG6 / R7.6).
_ACCOUNT_RE = re.compile(r"\b(?<!\d)\d{12}(?!\d)\b")
_VPC_RE = re.compile(r"\bvpc-[0-9a-f]{8,17}\b")
_SUBNET_RE = re.compile(r"\bsubnet-[0-9a-f]{8,17}\b")
_SG_RE = re.compile(r"\bsg-[0-9a-f]{8,17}\b")
_ARN_RE = re.compile(r"\barn:aws:[a-z0-9-]+:[a-z0-9-]+:\d{12}:")


def _db_event(resource_id: str, event_id: str | None = None) -> ChangeEvent:
    eid = event_id or make_event_id("database", "appuser@appdb", _TS, resource_id)
    return ChangeEvent(
        event_id=eid,
        source="database",
        actor="appuser@appdb",
        timestamp=_TS,
        engine="postgresql",
        resource_id=resource_id,
        severity="high",
        summary="ALTER on TABLE shop.orders (database-test): ALTER ...",
        details_url="cloudwatch:postgresql:database-test",
        raw_payload_ref="pgddl:stream:1",
    )


# --- SeededTicketSource ------------------------------------------------------


def test_seeded_source_loads_tickets_and_linkage() -> None:
    source = SeededTicketSource()
    all_tickets = source.all_tickets()
    assert len(all_tickets) >= 6
    ids = {t.ticket_id for t in all_tickets}
    assert "CHG-1042" in ids
    for t in all_tickets:
        assert t.data_origin == "seeded"
        assert t.status in {"open", "approved", "closed"}

    linkage = source.linkage()
    assert isinstance(linkage, TicketLinkage)
    # Pattern entries are (regex, ticket_id) tuples after loading.
    assert linkage.by_resource_pattern
    for pattern, ticket_id in linkage.by_resource_pattern:
        assert isinstance(pattern, str)
        assert isinstance(ticket_id, str)


def test_seeded_dataset_is_placeholder_only() -> None:
    # The bundled JSON must contain no AWS account id / ARN / VPC / subnet / SG.
    from src.admin_ops.kg.tickets import _SEEDED_DATA_PATH

    body = _SEEDED_DATA_PATH.read_text(encoding="utf-8")
    assert _ACCOUNT_RE.search(body) is None
    assert _VPC_RE.search(body) is None
    assert _SUBNET_RE.search(body) is None
    assert _SG_RE.search(body) is None
    assert _ARN_RE.search(body) is None


def test_seeded_linkage_resolves_known_table() -> None:
    source = SeededTicketSource()
    linkage = source.linkage()
    event = _db_event("pg_ddl:database-test:TABLE shop.orders")
    assert linkage.resolve(event) == "CHG-1042"


# --- integration seam (R7.3) -------------------------------------------------


class _IntegratedTicketSource(TicketSource):
    """Stub integration source: returns tickets with data_origin='integrated'."""

    def all_tickets(self) -> list[Ticket]:
        return [
            Ticket(
                ticket_id="CHG-1042",
                status="approved",
                title="Add note column to shop.orders",
                created_at=_TS,
                data_origin="integrated",
            )
        ]

    def linkage(self) -> TicketLinkage:
        return TicketLinkage(by_event_id={"abc": "CHG-1042"})


def test_integrated_source_works_through_same_interface() -> None:
    source: TicketSource = _IntegratedTicketSource()
    all_tickets = source.all_tickets()
    assert len(all_tickets) == 1
    assert all_tickets[0].data_origin == "integrated"
    # Same Ticket shape and same linkage interface as the seeded source.
    assert isinstance(source.linkage(), TicketLinkage)


def test_set_ticket_source_for_testing_seam() -> None:
    try:
        set_ticket_source_for_testing(_IntegratedTicketSource())
        active = get_ticket_source()
        assert isinstance(active, _IntegratedTicketSource)
        assert active.all_tickets()[0].data_origin == "integrated"
    finally:
        set_ticket_source_for_testing(None)
    # After reset the default seeded source is restored.
    assert isinstance(get_ticket_source(), SeededTicketSource)


# --- TicketLinkage.resolve precedence ----------------------------------------


def test_linkage_resolve_exact_event_id_first() -> None:
    event = _db_event("pg_ddl:database-test:TABLE shop.orders", event_id="EVT-1")
    linkage = TicketLinkage(
        by_event_id={"EVT-1": "CHG-2000"},
        by_resource_pattern=[(r"shop\.orders", "CHG-1042")],
    )
    # Exact event-id match wins over the pattern that would also match.
    assert linkage.resolve(event) == "CHG-2000"


def test_linkage_resolve_falls_back_to_pattern() -> None:
    event = _db_event("pg_ddl:database-test:TABLE shop.orders", event_id="EVT-1")
    linkage = TicketLinkage(by_resource_pattern=[(r"shop\.orders", "CHG-1042")])
    assert linkage.resolve(event) == "CHG-1042"


def test_linkage_resolve_returns_none_when_no_match() -> None:
    event = _db_event("pg_ddl:database-test:TABLE public.unknown", event_id="EVT-9")
    linkage = TicketLinkage(
        by_event_id={"OTHER": "CHG-2000"},
        by_resource_pattern=[(r"shop\.orders", "CHG-1042")],
    )
    assert linkage.resolve(event) is None


def test_linkage_resolve_first_matching_pattern_wins() -> None:
    event = _db_event("pg_ddl:database-test:TABLE shop.orders", event_id="EVT-1")
    linkage = TicketLinkage(
        by_resource_pattern=[
            (r"shop\.orders", "CHG-1042"),
            (r"database-test", "CHG-9999"),
        ]
    )
    assert linkage.resolve(event) == "CHG-1042"
