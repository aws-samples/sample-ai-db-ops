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

"""Seeded Ticket dataset + linkage + integration seam (R7.1-R7.3, R7.6, R3.8).

Tickets (a.k.a. Change_Requests) are the headline DBA value of this feature:
linking a ``ChangeEvent`` to the ticket that authorized it, and surfacing
unticketed high-severity DDL. Real ticketing integration is explicitly out of
scope, so the demo ships a *seeded* placeholder-only dataset behind a documented
integration seam (:class:`TicketSource`). A future real integration implements
the same interface and flips ``data_origin`` to ``"integrated"`` without
changing node type, edges, or UI (R7.3).

The :class:`Ticket` model mirrors the ``ChangeEvent`` style: pydantic
``BaseModel`` with ``extra="forbid"`` and a ``field_serializer`` that emits
``created_at`` as ISO-8601. :class:`TicketLinkage` is the concrete class
``ingest.py`` references under ``TYPE_CHECKING``; it is duck-typed there via its
``by_event_id`` / ``by_resource_pattern`` attributes, so those names are stable.

The seeded dataset is bundled at ``data/seeded_tickets.json`` and contains
placeholder-only values (``CHG-1042``, ``shop.orders``); it carries **no** AWS
account id, ARN, VPC/subnet/SG id, or alias (R7.6, P-KG6). It is loaded via a
``Path`` relative to this module, so no AWS or network access is involved.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Literal, Optional, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_serializer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.admin_ops.changefeed.change_event import ChangeEvent

# The bundled seeded dataset lives next to this module under data/.
_SEEDED_DATA_PATH = Path(__file__).resolve().parent / "data" / "seeded_tickets.json"


class Ticket(BaseModel):
    """One Change_Request that may have authorized a ChangeEvent (R3.8).

    ``data_origin`` distinguishes the seeded demo dataset from a future real
    integration; the rest of the graph (node type, edges, UI) is identical for
    either origin (R7.3).
    """

    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(min_length=1)
    status: str = Field(min_length=1)  # e.g. "open", "approved", "closed"
    title: str = Field(min_length=1, max_length=512)  # R3.8
    created_at: datetime  # ISO-8601 UTC
    data_origin: Literal["seeded", "integrated"] = "seeded"  # R3.8

    @field_serializer("created_at", when_used="json")
    def _serialize_created_at(self, value: datetime) -> str:
        return value.isoformat()


class TicketLinkage(BaseModel):
    """Maps a ChangeEvent to the Ticket that authorized it.

    Keyed by ``event_id`` first (exact), with a fallback ordered list of
    ``(regex, ticket_id)`` patterns matched against ``resource_id`` so seeded
    DDL on a known table links without per-event wiring (R7.2). ``ingest.py``
    duck-types this class via ``by_event_id`` / ``by_resource_pattern``; those
    attribute names must stay stable.
    """

    model_config = ConfigDict(extra="forbid")

    by_event_id: dict[str, str] = {}  # event_id -> ticket_id
    by_resource_pattern: list[tuple[str, str]] = []  # (regex, ticket_id)

    def resolve(self, event: "ChangeEvent") -> str | None:
        """Resolve a ``ticket_id`` for ``event``: exact, then pattern.

        First an exact ``by_event_id[event.event_id]`` lookup; then the first
        ``by_resource_pattern`` regex that matches ``event.resource_id``.
        Returns None when nothing matches. Exact wins over pattern (R7.2).
        """
        ticket_id = self.by_event_id.get(event.event_id)
        if ticket_id is not None:
            return ticket_id
        for pattern, candidate in self.by_resource_pattern:
            if re.search(pattern, event.resource_id):
                return candidate
        return None


class TicketSource(ABC):
    """Integration seam (R7.3).

    The demo ships :class:`SeededTicketSource`; a future real integration
    implements the same interface and sets ``data_origin = "integrated"``
    without changing node type, edges, or UI.
    """

    @abstractmethod
    def all_tickets(self) -> list[Ticket]:
        """Return every Ticket known to this source."""

    @abstractmethod
    def linkage(self) -> TicketLinkage:
        """Return the ChangeEvent -> Ticket linkage for this source."""


class SeededTicketSource(TicketSource):
    """Loads the placeholder-only seeded dataset bundled with the feature.

    Reads ``data/seeded_tickets.json`` (relative to this module) once and
    caches the parsed tickets and linkage. Every ticket it yields has
    ``data_origin == "seeded"``.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _SEEDED_DATA_PATH
        self._tickets: list[Ticket] | None = None
        self._linkage: TicketLinkage | None = None

    def _load(self) -> None:
        if self._tickets is not None and self._linkage is not None:
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        self._tickets = [Ticket.model_validate(t) for t in raw.get("tickets", [])]
        link = raw.get("linkage", {}) or {}
        # JSON arrays decode to lists; coerce the pattern pairs to tuples so the
        # duck-typed (regex, ticket_id) shape ingest.py expects holds.
        patterns = [tuple(pair) for pair in link.get("by_resource_pattern", [])]
        self._linkage = TicketLinkage(
            by_event_id=dict(link.get("by_event_id", {})),
            by_resource_pattern=patterns,
        )

    def all_tickets(self) -> list[Ticket]:
        self._load()
        assert self._tickets is not None  # for type-checkers; _load sets it
        return list(self._tickets)

    def linkage(self) -> TicketLinkage:
        self._load()
        assert self._linkage is not None  # for type-checkers; _load sets it
        return self._linkage


# ─── Source seam (mirrors store.set_backend_for_testing) ─────────────────────


_source: TicketSource | None = None
_lock = RLock()


def get_ticket_source() -> TicketSource:
    """Return the active :class:`TicketSource`.

    Defaults to :class:`SeededTicketSource`. Swappable for tests/integration
    via :func:`set_ticket_source_for_testing`, mirroring the store backend seam.
    """
    global _source
    with _lock:
        if _source is None:
            _source = SeededTicketSource()
        return _source


def set_ticket_source_for_testing(src: Optional[TicketSource]) -> None:
    """Override the active ticket source (tests/integration); None resets it."""
    global _source
    with _lock:
        _source = src
