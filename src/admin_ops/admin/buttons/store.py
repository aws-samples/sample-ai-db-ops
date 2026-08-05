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

"""DynamoDB-backed Custom_Button persistence.

The production backend uses boto3.resource('dynamodb'). Tests can swap in
an in-memory backend via `set_backend_for_testing`. Reorder is atomic:
the implementation uses TransactWriteItems so all positions update or
none do (R2.7).

Validates: R2.1, R2.2, R2.4, R2.7, R2.8, R2.9.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Iterable, Sequence
from uuid import UUID, uuid4

from src.admin_ops.admin.buttons.schema import (
    CustomButton,
    CustomButtonCreate,
    CustomButtonPatch,
    ReorderEntry,
)
from src.admin_ops.config.require import optional_config

LOG = logging.getLogger(__name__)
_TABLE_NAME = "dbops-custom-buttons"


class ButtonStoreUnreachable(RuntimeError):
    """Raised when the persistence backend is unreachable.

    Routes translate this to HTTP 503.
    """


class ButtonNotFound(KeyError):
    """Raised when a button_id is not in the caller's scope."""


# ─── Backend abstraction ────────────────────────────────────────────────────


class _ButtonBackend:
    def list_for_owner(
        self,
        owner_user_id: str,
        team_id: str | None,
        engine: str | None,
    ) -> list[CustomButton]:
        raise NotImplementedError

    def put(self, button: CustomButton) -> None:
        raise NotImplementedError

    def get(self, owner_user_id: str, button_id: UUID) -> CustomButton:
        raise NotImplementedError

    def delete(self, owner_user_id: str, button_id: UUID) -> None:
        raise NotImplementedError

    def transact_update_positions(
        self,
        owner_user_id: str,
        updates: Sequence[ReorderEntry],
    ) -> None:
        raise NotImplementedError


class _DynamoDbBackend(_ButtonBackend):  # pragma: no cover - exercised in deploy
    def __init__(self, table_name: str = _TABLE_NAME, region: str | None = None) -> None:
        import boto3

        self._region = region or os.environ.get("AWS_REGION") or optional_config(
            "account", "region", default="us-east-1"
        )
        self._dynamodb = boto3.resource("dynamodb", region_name=self._region)
        self._table = self._dynamodb.Table(table_name)
        self._client = boto3.client("dynamodb", region_name=self._region)

    @staticmethod
    def _safe(fn: Any, *args: Any, **kw: Any) -> Any:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return fn(*args, **kw)
        except (BotoCoreError, ClientError) as exc:
            raise ButtonStoreUnreachable(str(exc)) from exc

    @staticmethod
    def _to_item(button: CustomButton) -> dict[str, Any]:
        out = button.model_dump(mode="json")
        out["button_id"] = str(button.button_id)
        out["position_button_id"] = f"{button.position:08d}#{out['button_id']}"
        return out

    @staticmethod
    def _from_item(item: dict[str, Any]) -> CustomButton:
        item = {k: v for k, v in item.items() if k != "position_button_id"}
        return CustomButton.model_validate(item)

    def list_for_owner(
        self,
        owner_user_id: str,
        team_id: str | None,
        engine: str | None,
    ) -> list[CustomButton]:
        kw: dict[str, Any] = {
            "KeyConditionExpression": "owner_user_id = :uid",
            "ExpressionAttributeValues": {":uid": owner_user_id},
            "Limit": 200,
        }
        if engine:
            kw["FilterExpression"] = "engine = :eng"
            kw["ExpressionAttributeValues"][":eng"] = engine
        resp = self._safe(self._table.query, **kw)
        items = [self._from_item(i) for i in resp.get("Items", [])]
        if team_id:
            # Augment with team-scoped buttons via the GSI.
            gsi = self._safe(
                self._table.query,
                IndexName="team_id-index",
                KeyConditionExpression="team_id = :tid",
                ExpressionAttributeValues={":tid": team_id},
                Limit=200,
            )
            items.extend(self._from_item(i) for i in gsi.get("Items", []))
        items.sort(key=lambda b: (b.position, b.created_at))
        return items

    def put(self, button: CustomButton) -> None:
        self._safe(self._table.put_item, Item=self._to_item(button))

    def get(self, owner_user_id: str, button_id: UUID) -> CustomButton:
        # Need a query because position_button_id is opaque from caller's view.
        resp = self._safe(
            self._table.query,
            KeyConditionExpression="owner_user_id = :uid",
            FilterExpression="button_id = :bid",
            ExpressionAttributeValues={":uid": owner_user_id, ":bid": str(button_id)},
        )
        items = resp.get("Items", [])
        if not items:
            raise ButtonNotFound(str(button_id))
        return self._from_item(items[0])

    def delete(self, owner_user_id: str, button_id: UUID) -> None:
        existing = self.get(owner_user_id, button_id)
        sk = f"{existing.position:08d}#{button_id}"
        self._safe(
            self._table.delete_item,
            Key={"owner_user_id": owner_user_id, "position_button_id": sk},
        )

    def transact_update_positions(
        self,
        owner_user_id: str,
        updates: Sequence[ReorderEntry],
    ) -> None:
        if not updates:
            return
        existing = {u.button_id: self.get(owner_user_id, u.button_id) for u in updates}
        # DynamoDB doesn't support updating part of a composite key in place,
        # so we PutItem with the new position SK and DeleteItem the old.
        items: list[dict[str, Any]] = []
        for u in updates:
            cur = existing[u.button_id]
            new_button = cur.model_copy(update={"position": u.position, "updated_at": _utc_now()})
            old_sk = f"{cur.position:08d}#{cur.button_id}"
            new_sk = f"{u.position:08d}#{new_button.button_id}"
            new_dyn = self._to_item(new_button)
            items.append(
                {
                    "Delete": {
                        "TableName": _TABLE_NAME,
                        "Key": {
                            "owner_user_id": {"S": owner_user_id},
                            "position_button_id": {"S": old_sk},
                        },
                    }
                }
            )
            items.append(
                {
                    "Put": {
                        "TableName": _TABLE_NAME,
                        "Item": _to_dynamodb_item(new_dyn),
                    }
                }
            )
        self._safe(self._client.transact_write_items, TransactItems=items)


def _to_dynamodb_item(d: dict[str, Any]) -> dict[str, Any]:
    """Minimal Python dict → DynamoDB attribute map conversion."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = {"BOOL": v}
        elif isinstance(v, int):
            out[k] = {"N": str(v)}
        elif isinstance(v, str):
            out[k] = {"S": v}
        elif isinstance(v, list):
            out[k] = {"L": [_to_attr(item) for item in v]}
        elif isinstance(v, dict):
            out[k] = {"M": {kk: _to_attr(vv) for kk, vv in v.items()}}
        else:
            out[k] = {"S": str(v)}
    return out


def _to_attr(v: Any) -> dict[str, Any]:
    if isinstance(v, bool):
        return {"BOOL": v}
    if isinstance(v, int):
        return {"N": str(v)}
    if isinstance(v, str):
        return {"S": v}
    return {"S": str(v)}


# ─── Module state ───────────────────────────────────────────────────────────


_backend: _ButtonBackend | None = None
_lock = RLock()


def _get_backend() -> _ButtonBackend:
    global _backend
    with _lock:
        if _backend is None:
            # Local-dev escape: when ADMIN_DEV_BYPASS=1 (set in
            # ui/.env.local for demos), persist to a JSON file instead
            # of DynamoDB so the demo doesn't need the
            # `dbops-custom-buttons` table to exist in AWS.
            if os.environ.get("ADMIN_DEV_BYPASS") == "1":
                from src.admin_ops.admin.buttons._dev_store import (
                    JsonFileButtonBackend,
                )

                _backend = JsonFileButtonBackend()
            else:
                _backend = _DynamoDbBackend()
        return _backend


def set_backend_for_testing(backend: _ButtonBackend | None) -> None:
    global _backend
    with _lock:
        _backend = backend


# ─── Public API ─────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def list_buttons(
    owner_user_id: str,
    team_id: str | None = None,
    engine: str | None = None,
) -> list[CustomButton]:
    if not owner_user_id:
        raise ValueError("owner_user_id is required")
    return _get_backend().list_for_owner(owner_user_id, team_id, engine)


def create_button(
    owner_user_id: str,
    payload: CustomButtonCreate,
    *,
    next_position: int | None = None,
) -> CustomButton:
    """Create a new CustomButton.

    `next_position` defaults to the current max position + 1, computed by
    listing the owner's buttons. Callers can pass an explicit position
    when constructing fixtures.
    """
    if not owner_user_id:
        raise ValueError("owner_user_id is required")
    if next_position is None:
        existing = _get_backend().list_for_owner(owner_user_id, payload.team_id, None)
        next_position = (max((b.position for b in existing), default=-1)) + 1
    now = _utc_now()
    button = CustomButton(
        button_id=uuid4(),
        owner_user_id=owner_user_id,
        team_id=payload.team_id,
        label=payload.label,
        icon=payload.icon,
        engine=payload.engine,
        target_scope=payload.target_scope,
        body_kind=payload.body_kind,
        body=payload.body,
        confirmation_required=payload.confirmation_required,
        tier_hint=payload.tier_hint,
        position=next_position,
        created_at=now,
        updated_at=now,
    )
    _get_backend().put(button)
    return button


def get_button(owner_user_id: str, button_id: UUID) -> CustomButton:
    return _get_backend().get(owner_user_id, button_id)


def update_button(
    owner_user_id: str,
    button_id: UUID,
    patch: CustomButtonPatch,
) -> CustomButton:
    cur = _get_backend().get(owner_user_id, button_id)
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        return cur
    new_button = cur.model_copy(update={**fields, "updated_at": _utc_now()})
    _get_backend().put(new_button)
    return new_button


def delete_button(owner_user_id: str, button_id: UUID) -> None:
    _get_backend().delete(owner_user_id, button_id)


def reorder_buttons(owner_user_id: str, updates: Iterable[ReorderEntry]) -> None:
    """Atomically re-assign positions on a set of buttons.

    Either every position update lands or none of them do.
    """
    seq = list(updates)
    if not seq:
        return
    _get_backend().transact_update_positions(owner_user_id, seq)
