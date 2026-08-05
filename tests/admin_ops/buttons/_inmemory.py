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

"""In-memory ButtonBackend for tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from src.admin_ops.admin.buttons.schema import CustomButton, ReorderEntry
from src.admin_ops.admin.buttons.store import ButtonNotFound, _ButtonBackend


class InMemoryButtonBackend(_ButtonBackend):
    def __init__(self) -> None:
        # Keyed by (owner_user_id, button_id)
        self._records: dict[tuple[str, UUID], CustomButton] = {}

    def list_for_owner(
        self,
        owner_user_id: str,
        team_id: str | None,
        engine: str | None,
    ) -> list[CustomButton]:
        out: list[CustomButton] = []
        for (uid, _), b in self._records.items():
            if uid != owner_user_id and b.team_id != team_id:
                continue
            if engine and b.engine != engine:
                continue
            out.append(b)
        out.sort(key=lambda b: (b.position, b.created_at))
        return out

    def put(self, button: CustomButton) -> None:
        self._records[(button.owner_user_id, button.button_id)] = button

    def get(self, owner_user_id: str, button_id: UUID) -> CustomButton:
        b = self._records.get((owner_user_id, button_id))
        if b is None:
            raise ButtonNotFound(str(button_id))
        return b

    def delete(self, owner_user_id: str, button_id: UUID) -> None:
        self._records.pop((owner_user_id, button_id), None)

    def transact_update_positions(
        self,
        owner_user_id: str,
        updates: Sequence[ReorderEntry],
    ) -> None:
        # In-memory model — simulate atomicity by validating first, then mutating.
        for u in updates:
            if (owner_user_id, u.button_id) not in self._records:
                raise ButtonNotFound(str(u.button_id))
        now = datetime.now(timezone.utc)
        for u in updates:
            cur = self._records[(owner_user_id, u.button_id)]
            self._records[(owner_user_id, u.button_id)] = cur.model_copy(
                update={"position": u.position, "updated_at": now}
            )
