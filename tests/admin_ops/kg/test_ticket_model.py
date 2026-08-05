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

"""Property S6 (R3.8) — Ticket model invariant.

For any Ticket produced by a TicketSource, ticket_id / status / title /
created_at are present, title length is in 1..512, and data_origin in
{seeded, integrated}; the SeededTicketSource always yields data_origin="seeded".
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg.tickets import (
    SeededTicketSource,
    Ticket,
    TicketLinkage,
    TicketSource,
)

_ORIGINS = ["seeded", "integrated"]
_STATUSES = ["open", "approved", "closed"]
_TIMESTAMPS = st.datetimes(
    min_value=datetime(2015, 1, 1),
    max_value=datetime(2030, 1, 1),
    timezones=st.just(timezone.utc),
)


@st.composite
def tickets(draw: st.DrawFn) -> Ticket:
    """An arbitrary valid Ticket, including boundary-length titles."""
    title = draw(st.text(min_size=1, max_size=512))
    return Ticket(
        ticket_id=draw(st.text(min_size=1, max_size=32)),
        status=draw(st.sampled_from(_STATUSES)),
        title=title,
        created_at=draw(_TIMESTAMPS),
        data_origin=draw(st.sampled_from(_ORIGINS)),
    )


class _StubTicketSource(TicketSource):
    """A TicketSource backed by an arbitrary list of tickets (for the property)."""

    def __init__(self, items: list[Ticket]) -> None:
        self._items = items

    def all_tickets(self) -> list[Ticket]:
        return list(self._items)

    def linkage(self) -> TicketLinkage:
        return TicketLinkage()


# Feature: dba-knowledge-graph, Property S6: Ticket model invariant
@settings(deadline=None, max_examples=200)
@given(items=st.lists(tickets(), max_size=12))
def test_s6_ticket_model_invariant(items: list[Ticket]) -> None:
    source = _StubTicketSource(items)
    for t in source.all_tickets():
        assert t.ticket_id
        assert t.status
        assert t.title
        assert isinstance(t.created_at, datetime)
        assert 1 <= len(t.title) <= 512
        assert t.data_origin in {"seeded", "integrated"}


# Feature: dba-knowledge-graph, Property S6: SeededTicketSource yields seeded only
@settings(deadline=None, max_examples=50)
@given(_=st.just(None))
def test_s6_seeded_source_always_seeded(_: None) -> None:
    source = SeededTicketSource()
    all_tickets = source.all_tickets()
    assert all_tickets, "seeded dataset must not be empty"
    for t in all_tickets:
        assert t.data_origin == "seeded"
        assert 1 <= len(t.title) <= 512
