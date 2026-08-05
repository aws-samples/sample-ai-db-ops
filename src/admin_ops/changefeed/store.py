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

"""Change_Feed persistence, dedup, and filtering (R4.6, R4.10, R4.11).

The production backend uses ``boto3.resource('dynamodb')`` against the
``dbops-change-feed`` table. Tests swap in an in-memory backend via
:func:`set_backend_for_testing`, exactly like the Custom_Button store.

boto3 is imported lazily inside :class:`_DynamoDbBackend` so importing this
module never requires AWS connectivity.

Validates: R4.6 (dedup), R4.10 (reverse-chronological pagination),
R4.11 (AND-across / OR-within filter composition; confluent — P11).
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.admin_ops.changefeed.change_event import (
    ChangeEvent,
    Engine,
    Severity,
    Source,
)

LOG = logging.getLogger(__name__)
_TABLE_NAME = "dbops-change-feed"
_MAX_VALUES_PER_CATEGORY = 10


class ChangeFeedUnreachable(RuntimeError):
    """Raised when the persistence backend is unreachable.

    Routes translate this to HTTP 503.
    """


# ─── Filter model ───────────────────────────────────────────────────────────


class ChangeFeedFilter(BaseModel):
    """A Change_Feed query filter.

    Semantics (R4.11): AND across categories, OR within a category. Up to 10
    selected values per category; >10 raises at construction time. The time
    range is inclusive on both ends.
    """

    model_config = ConfigDict(extra="forbid")

    sources: list[Source] | None = None
    engines: list[Engine] | None = None
    severities: list[Severity] | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None

    @field_validator("sources", "engines", "severities")
    @classmethod
    def _at_most_ten(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) > _MAX_VALUES_PER_CATEGORY:
            raise ValueError(
                f"at most {_MAX_VALUES_PER_CATEGORY} values allowed per filter category"
            )
        return v

    def matches(self, e: ChangeEvent) -> bool:
        """Return True if ``e`` satisfies every active category (AND across).

        Within a category, membership is an OR over the selected values.
        """
        if self.sources is not None and e.source not in self.sources:
            return False
        if self.engines is not None and e.engine not in self.engines:
            return False
        if self.severities is not None and e.severity not in self.severities:
            return False
        if self.time_from is not None and e.timestamp < self.time_from:
            return False
        if self.time_to is not None and e.timestamp > self.time_to:
            return False
        return True


# ─── Pure helpers ───────────────────────────────────────────────────────────


def dedupe(events: list[ChangeEvent]) -> list[ChangeEvent]:
    """Keep only the first occurrence of each ``event_id`` (R4.6).

    Preserves the order of first appearance.
    """
    seen: set[str] = set()
    out: list[ChangeEvent] = []
    for e in events:
        if e.event_id in seen:
            continue
        seen.add(e.event_id)
        out.append(e)
    return out


def apply_filter(f: ChangeFeedFilter, events: list[ChangeEvent]) -> list[ChangeEvent]:
    """Return the events matching ``f``, preserving input order (R4.11).

    Pure function. Because it is an order-preserving predicate filter,
    composition is confluent:
    ``apply_filter(f2, apply_filter(f1, L)) == apply_filter(f1, apply_filter(f2, L))``
    (property P11).
    """
    return [e for e in events if f.matches(e)]


def _paginate_reverse_chrono(
    events: list[ChangeEvent],
    page: int,
    page_size: int,
) -> dict:
    """Sort reverse-chronologically by timestamp and slice one page (R4.10)."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    # Tie-break on event_id so equal timestamps yield a stable order.
    ordered = sorted(events, key=lambda e: (e.timestamp, e.event_id), reverse=True)
    total = len(ordered)
    total_pages = math.ceil(total / page_size)
    start = (page - 1) * page_size
    window = ordered[start : start + page_size]
    return {"events": window, "page": page, "total_pages": total_pages}


# ─── Backend abstraction ────────────────────────────────────────────────────


class _ChangeFeedBackend:
    def put_event(self, event: ChangeEvent) -> bool:
        raise NotImplementedError

    def all_events(self) -> list[ChangeEvent]:
        raise NotImplementedError

    def query(self, filters: ChangeFeedFilter, page: int, page_size: int) -> dict:
        # Default implementation: filter + dedupe + paginate over all events.
        deduped = dedupe(self.all_events())
        filtered = apply_filter(filters, deduped)
        return _paginate_reverse_chrono(filtered, page, page_size)


class _DynamoDbBackend(_ChangeFeedBackend):  # pragma: no cover - exercised in deploy
    def __init__(self, table_name: str = _TABLE_NAME, region: str | None = None) -> None:
        import boto3

        from src.admin_ops.config.require import optional_config

        self._region = (
            region
            or os.environ.get("AWS_REGION")
            or optional_config("account", "region", default="us-east-1")
        )
        self._dynamodb = boto3.resource("dynamodb", region_name=self._region)
        self._table = self._dynamodb.Table(table_name)

    @staticmethod
    def _safe(fn: Any, *args: Any, **kw: Any) -> Any:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return fn(*args, **kw)
        except (BotoCoreError, ClientError) as exc:
            raise ChangeFeedUnreachable(str(exc)) from exc

    @staticmethod
    def _event_date(event: ChangeEvent) -> str:
        return event.timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _sort_key(event: ChangeEvent) -> str:
        return f"{event.timestamp.isoformat()}#{event.event_id}"

    def _to_item(self, event: ChangeEvent) -> dict[str, Any]:
        item = event.model_dump(mode="json")
        item["event_date"] = self._event_date(event)
        item["sk"] = self._sort_key(event)
        expires = event.timestamp.astimezone(timezone.utc) + timedelta(days=365)
        item["expires_at"] = int(expires.timestamp())
        return item

    @staticmethod
    def _from_item(item: dict[str, Any]) -> ChangeEvent:
        data = {k: v for k, v in item.items() if k not in {"event_date", "sk", "expires_at"}}
        return ChangeEvent.model_validate(data)

    def put_event(self, event: ChangeEvent) -> bool:
        # Idempotent: only write when this event_id is not already stored.
        item = self._to_item(event)
        try:
            self._safe(
                self._table.put_item,
                Item=item,
                ConditionExpression="attribute_not_exists(event_id)",
            )
            return True
        except ChangeFeedUnreachable as exc:
            from botocore.exceptions import ClientError

            cause = exc.__cause__
            if isinstance(cause, ClientError) and (
                cause.response.get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                return False
            raise

    def all_events(self) -> list[ChangeEvent]:
        resp = self._safe(self._table.scan, Limit=1000)
        return [self._from_item(i) for i in resp.get("Items", [])]


# ─── Module state ───────────────────────────────────────────────────────────


_backend: _ChangeFeedBackend | None = None
_lock = RLock()


def _get_backend() -> _ChangeFeedBackend:
    global _backend
    with _lock:
        if _backend is None:
            # Local-dev escape: when ADMIN_DEV_BYPASS=1 (set in
            # ui/.env.local for demos), persist to a JSON file instead of
            # DynamoDB so the change feed works without the
            # `dbops-change-feed` table existing in AWS.
            if os.environ.get("ADMIN_DEV_BYPASS") == "1":
                from src.admin_ops.changefeed._dev_store import (
                    JsonFileChangeFeedBackend,
                )

                _backend = JsonFileChangeFeedBackend()
            else:
                _backend = _DynamoDbBackend()
        return _backend


def set_backend_for_testing(backend: _ChangeFeedBackend | None) -> None:
    global _backend
    with _lock:
        _backend = backend


# ─── Public API ─────────────────────────────────────────────────────────────


def put_event(event: ChangeEvent) -> bool:
    """Idempotently persist a Change_Event (R4.6, P10).

    Returns True when the event is newly written, False when an event with
    the same ``event_id`` already existed.
    """
    return _get_backend().put_event(event)


def query(
    filters: ChangeFeedFilter,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Return a page of Change_Events in reverse-chronological order (R4.10).

    Result shape: ``{"events": [...], "page": page, "total_pages": N}``.
    """
    return _get_backend().query(filters, page, page_size)
