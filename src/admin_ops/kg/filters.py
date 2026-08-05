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

"""Filter algebra + timeline ordering over ChangeEvents (R6.2-R6.5).

Pure, order-independent functions used by the DBA View timeline and graph
panes. The browser mirrors this exact logic in ``ui/src/lib/dba/filters.ts``.

Filter semantics (R6.3, R6.4):

* **AND across** the categories database / principal / severity / source /
  time-range: an event must satisfy *every* active category.
* **OR within** a category: an event satisfies a category if its value is in
  the selected set for that category.
* **DDL-only toggle** (R6.4): when set, restricts to events whose ``ddl_kind``
  is set (i.e. ``ddl_kind_of`` returns a verb).
* An unset category imposes no constraint.

Because :func:`apply` is an order-preserving predicate filter, composition is
confluent: ``apply(f2, apply(f1, L)) == apply(f1, apply(f2, L))`` (P-KG4). The
predicate set is exactly the events satisfying all active categories (S4).

Timeline ordering (R6.2, S5): :func:`order_timeline` sorts reverse-
chronologically by ``timestamp`` with a stable tie-break on ``event_id`` and
paginates at a fixed 50 per page.

``database`` and ``principal`` are derived from the event with the same
helpers the mapper uses (``parse_resource`` / ``actor``) so the filter and the
graph agree on identity.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, field_validator

from src.admin_ops.changefeed.change_event import ChangeEvent, Severity, Source
from src.admin_ops.kg.ingest import ddl_kind_of, parse_resource

# Fixed page size for the DBA timeline (R6.2, S5).
PAGE_SIZE = 50
_MAX_VALUES_PER_CATEGORY = 50


def event_database(event: ChangeEvent) -> str | None:
    """Return the database identifier for an event, or None.

    Uses the same ``parse_resource`` the mapper uses so the timeline filter and
    the graph nodes agree on database identity.
    """
    db, _table = parse_resource(event)
    return db


def event_principal(event: ChangeEvent) -> str:
    """Return the principal (actor) for an event."""
    return event.actor


class EventFilter(BaseModel):
    """A DBA timeline/graph filter (R6.3, R6.4).

    AND across categories, OR within each category. ``None`` means the category
    is inactive (no constraint). ``ddl_only`` restricts to DDL events. The time
    range is inclusive on both ends.
    """

    model_config = ConfigDict(extra="forbid")

    databases: list[str] | None = None
    principals: list[str] | None = None
    severities: list[Severity] | None = None
    sources: list[Source] | None = None
    time_from: object | None = None  # datetime; typed loosely to avoid import churn
    time_to: object | None = None
    ddl_only: bool = False

    @field_validator("databases", "principals", "severities", "sources")
    @classmethod
    def _at_most_max(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) > _MAX_VALUES_PER_CATEGORY:
            raise ValueError(
                f"at most {_MAX_VALUES_PER_CATEGORY} values allowed per category"
            )
        return v

    def matches(self, e: ChangeEvent) -> bool:
        """True iff ``e`` satisfies every active category (AND across).

        Within a category, membership is an OR over the selected values.
        """
        if self.databases is not None and event_database(e) not in self.databases:
            return False
        if self.principals is not None and event_principal(e) not in self.principals:
            return False
        if self.severities is not None and e.severity not in self.severities:
            return False
        if self.sources is not None and e.source not in self.sources:
            return False
        if self.time_from is not None and e.timestamp < self.time_from:
            return False
        if self.time_to is not None and e.timestamp > self.time_to:
            return False
        if self.ddl_only and ddl_kind_of(e) is None:
            return False
        return True


def apply(f: EventFilter, events: list[ChangeEvent]) -> list[ChangeEvent]:
    """Return the events matching ``f``, preserving input order (R6.3-R6.5).

    Pure, order-preserving predicate filter, so composition is confluent
    (P-KG4): ``apply(f2, apply(f1, L)) == apply(f1, apply(f2, L))``.
    """
    return [e for e in events if f.matches(e)]


def order_timeline(
    events: list[ChangeEvent],
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict:
    """Reverse-chronological page of ``events`` (R6.2, S5).

    Ordered by ``timestamp`` descending with a stable tie-break on ``event_id``;
    at most ``page_size`` (default 50) per page. Result shape:
    ``{"events": [...], "page": page, "total_pages": N}``.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    ordered = sorted(events, key=lambda e: (e.timestamp, e.event_id), reverse=True)
    total = len(ordered)
    total_pages = math.ceil(total / page_size) if total else 0
    start = (page - 1) * page_size
    window = ordered[start : start + page_size]
    return {"events": window, "page": page, "total_pages": total_pages}
