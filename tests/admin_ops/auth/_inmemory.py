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

"""In-memory backend for `src.admin_ops.admin.role` used by tests."""

from __future__ import annotations

from datetime import datetime, timezone

from src.admin_ops.admin.role import AdminRecord, AdminSourceUnreachable, _AdminBackend


class InMemoryBackend(_AdminBackend):
    def __init__(self, raise_on_call: bool = False) -> None:
        self._records: dict[str, AdminRecord] = {}
        self.raise_on_call = raise_on_call

    def _maybe_raise(self) -> None:
        if self.raise_on_call:
            raise AdminSourceUnreachable("simulated DynamoDB outage")

    def is_admin(self, user_id: str) -> bool:
        self._maybe_raise()
        return user_id in self._records

    def list(self) -> list[AdminRecord]:
        self._maybe_raise()
        return list(self._records.values())

    def grant(self, user_id: str, granted_by: str, note: str = "") -> None:
        self._maybe_raise()
        self._records[user_id] = AdminRecord(
            user_id=user_id,
            granted_by=granted_by,
            granted_at=datetime.now(timezone.utc).isoformat(),
            note=note,
        )

    def revoke(self, user_id: str) -> None:
        self._maybe_raise()
        self._records.pop(user_id, None)

    def is_empty(self) -> bool:
        self._maybe_raise()
        return not self._records
