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

"""Admin role resolution backed by the `dbops-admins` DynamoDB table.

The Admin_Role marker resolves a `user_id` (the value of
`NEXT_PUBLIC_USER_ID` in the UI session) to a Boolean `is_admin`. The
table is the single source of truth (R6.2). When the table is empty,
`bootstrap_default()` inserts the user named in
`config.yaml::ui.default_user_id` once (R6.5).

A 60-second LRU cache keeps the resolution latency under 500 ms (R6.1).
The cache is invalidated whenever a grant or revoke is performed by this
process; cross-process invalidation is best-effort (other Next.js servers
will pick up the new state on cache expiry).

Validates: R6.1, R6.2, R6.3, R6.5, R6.7, R6.8.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any

from src.admin_ops.config.require import optional_config

LOG = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
# Default admins table name. The CloudFormation resource is named
# `${EnvironmentName}-admins` with EnvironmentName defaulting to `dbops`, so
# the deployed default is `dbops-admins`. The concrete name is resolved at
# runtime by `_resolve_table_name()` from env/config — never hardcoded to an
# account-scoped value (R7.1, R7.2).
_DEFAULT_TABLE_NAME = "dbops-admins"


def _resolve_table_name() -> str:
    """Resolve the `dbops-admins` table name from env/config (R7.2).

    Resolution order (first match wins), consistent with how sibling
    `admin_ops` stores resolve account-scoped values:

      1. ``ADMIN_TABLE_NAME`` env var — explicit override.
      2. ``${ENVIRONMENT_NAME}-admins`` when ``ENVIRONMENT_NAME`` is set —
         mirrors the CloudFormation table name ``${EnvironmentName}-admins``.
      3. ``config.yaml::admin.table_name``.
      4. The default ``dbops-admins`` (matches the CFN default EnvironmentName).
    """
    explicit = os.environ.get("ADMIN_TABLE_NAME")
    if explicit:
        return explicit
    env_name = os.environ.get("ENVIRONMENT_NAME")
    if env_name:
        return f"{env_name}-admins"
    return optional_config("admin", "table_name", default=_DEFAULT_TABLE_NAME)


class AdminSourceUnreachable(RuntimeError):
    """Raised when the admin source of truth cannot be reached.

    The middleware translates this to HTTP 503 per R6.7.
    """


class InvalidUserId(ValueError):
    """Raised when `user_id` is missing, empty, or out of bounds (R6.8)."""


@dataclass(frozen=True)
class AdminRecord:
    user_id: str
    granted_by: str
    granted_at: str
    note: str = ""


# ─── Backend abstraction ────────────────────────────────────────────────────

class _AdminBackend:
    """Pluggable backend; the production implementation is DynamoDB-backed.

    Tests can substitute an in-memory backend without touching AWS.
    """

    def is_admin(self, user_id: str) -> bool:
        raise NotImplementedError

    def list(self) -> list[AdminRecord]:
        raise NotImplementedError

    def grant(self, user_id: str, granted_by: str, note: str = "") -> None:
        raise NotImplementedError

    def revoke(self, user_id: str) -> None:
        raise NotImplementedError

    def is_empty(self) -> bool:
        raise NotImplementedError


class _DynamoDbBackend(_AdminBackend):
    """Real backend using boto3.resource('dynamodb')."""

    def __init__(self, table_name: str | None = None, region: str | None = None) -> None:
        import boto3  # local import — keeps unit tests boto3-free

        self._table_name = table_name or _resolve_table_name()
        self._region = region or os.environ.get("AWS_REGION") or optional_config(
            "account", "region", default="us-east-1"
        )
        self._table = boto3.resource("dynamodb", region_name=self._region).Table(
            self._table_name
        )

    def _safe_call(self, fn: Any, *args: Any, **kw: Any) -> Any:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return fn(*args, **kw)
        except (BotoCoreError, ClientError) as exc:
            LOG.warning("%s backend error: %s", self._table_name, exc)
            raise AdminSourceUnreachable(str(exc)) from exc

    def is_admin(self, user_id: str) -> bool:
        resp = self._safe_call(self._table.get_item, Key={"user_id": user_id})
        return "Item" in resp

    def list(self) -> list[AdminRecord]:
        resp = self._safe_call(self._table.scan)
        return [AdminRecord(**item) for item in resp.get("Items", [])]

    def grant(self, user_id: str, granted_by: str, note: str = "") -> None:
        from datetime import datetime, timezone

        self._safe_call(
            self._table.put_item,
            Item={
                "user_id": user_id,
                "granted_by": granted_by,
                "granted_at": datetime.now(timezone.utc).isoformat(),
                "note": note,
            },
        )

    def revoke(self, user_id: str) -> None:
        self._safe_call(self._table.delete_item, Key={"user_id": user_id})

    def is_empty(self) -> bool:
        resp = self._safe_call(self._table.scan, Limit=1)
        return len(resp.get("Items", [])) == 0


# ─── Module-level state ─────────────────────────────────────────────────────

_backend: _AdminBackend | None = None
_cache: dict[str, tuple[bool, float]] = {}
_lock = RLock()


def _get_backend() -> _AdminBackend:
    global _backend
    with _lock:
        if _backend is None:
            _backend = _DynamoDbBackend()
        return _backend


def set_backend_for_testing(backend: _AdminBackend | None) -> None:
    """Inject a backend (e.g. in-memory) for tests; `None` resets."""
    global _backend
    with _lock:
        _backend = backend
        _cache.clear()


def _invalidate_cache(user_id: str | None = None) -> None:
    with _lock:
        if user_id is None:
            _cache.clear()
        else:
            _cache.pop(user_id, None)


# ─── Public API ─────────────────────────────────────────────────────────────


def _validate_user_id(user_id: str | None) -> str:
    if user_id is None or not isinstance(user_id, str):
        raise InvalidUserId("user_id is missing")
    if not user_id or len(user_id) > 128:
        raise InvalidUserId("user_id length must be 1..128")
    return user_id


def is_admin(user_id: str | None) -> bool:
    """Resolve a user_id to is_admin. Validates length first.

    Demo bypass: when ``ADMIN_DEV_BYPASS=1`` is set in the environment, a
    validated user_id resolves to admin WITHOUT touching the ``dbops-admins``
    table. This is the documented local-dev / hosted-demo escape hatch
    (see ``ui/.env.local``) that lets the admin-gated DBA View run fully
    in-process with no AWS dependency.

    SECURITY: this flag is a deliberate authorization bypass. It MUST NEVER be
    set in a real production deployment — production leaves ``ADMIN_DEV_BYPASS``
    unset so every request is resolved against the table source of truth (R6.2).
    The flag is the single source of truth for the bypass (independent of
    NODE_ENV) so the demo container behaves predictably.
    """
    uid = _validate_user_id(user_id)
    if os.environ.get("ADMIN_DEV_BYPASS") == "1":
        return True
    now = time.monotonic()
    with _lock:
        cached = _cache.get(uid)
        if cached is not None and (now - cached[1]) < _CACHE_TTL_SECONDS:
            return cached[0]
    backend = _get_backend()
    result = backend.is_admin(uid)
    with _lock:
        _cache[uid] = (result, now)
    return result


def grant(user_id: str, granted_by: str, note: str = "") -> None:
    """Insert a record into the admins table; invalidate the cache.

    Caller is responsible for emitting the Change_Event (task 4.1+).
    """
    uid = _validate_user_id(user_id)
    if not (0 <= len(note) <= 500):
        raise ValueError("note must be 0..500 chars")
    if not (1 <= len(granted_by) <= 128):
        raise ValueError("granted_by must be 1..128 chars")
    _get_backend().grant(uid, granted_by, note)
    _invalidate_cache(uid)


def revoke(user_id: str) -> None:
    """Remove a record; invalidate cache."""
    uid = _validate_user_id(user_id)
    _get_backend().revoke(uid)
    _invalidate_cache(uid)


def list_admins() -> list[AdminRecord]:
    return _get_backend().list()


def bootstrap_default() -> str | None:
    """If the admins table is empty, insert `ui.default_user_id` as admin.

    Returns the bootstrapped user_id, or None if the table already had
    records. Raises AdminSourceUnreachable on backend errors. (R6.5)
    """
    backend = _get_backend()
    if not backend.is_empty():
        return None
    default_uid = optional_config("ui", "default_user_id", default=None)
    if not default_uid:
        LOG.warning("dbops-admins is empty and ui.default_user_id is not set; skipping bootstrap")
        return None
    backend.grant(default_uid, "bootstrap", note="initial admin from config.yaml::ui.default_user_id")
    LOG.info("Bootstrapped admin from config.yaml: %s", default_uid)
    return default_uid
