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

"""Local-dev backend for the buttons store.

Activated when ADMIN_DEV_BYPASS=1 — persists to a single JSON file under
the user's home directory so demos survive Next.js dev-server restarts.
This module is **not** imported in production paths; the
`_get_backend` function in `store.py` only swaps it in when the env var
is set.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Sequence
from uuid import UUID

from src.admin_ops.admin.buttons.schema import CustomButton, ReorderEntry
from src.admin_ops.admin.buttons.store import ButtonNotFound, _ButtonBackend


def _state_file() -> Path:
    override = os.environ.get("ADMIN_DEV_STATE_FILE")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    target = base / "dbops" / "dev_buttons.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


class JsonFileButtonBackend(_ButtonBackend):
    """JSON-file-backed backend used only when ADMIN_DEV_BYPASS=1."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _state_file()
        self._lock = RLock()

    # ─── helpers ────────────────────────────────────────────────────────

    def _load(self) -> list[CustomButton]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        out: list[CustomButton] = []
        for item in raw:
            try:
                out.append(CustomButton.model_validate(item))
            except Exception:
                # Skip records that don't validate; do not crash the demo.
                continue
        return out

    def _save(self, buttons: list[CustomButton]) -> None:
        payload = [b.model_dump(mode="json") for b in buttons]
        # `default=str` covers UUID + datetime stragglers if a caller
        # ever bypasses model_dump(mode="json").
        self._path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

    # ─── _ButtonBackend interface ───────────────────────────────────────

    def list_for_owner(
        self,
        owner_user_id: str,
        team_id: str | None,
        engine: str | None,
    ) -> list[CustomButton]:
        with self._lock:
            buttons = self._load()
        out: list[CustomButton] = []
        for b in buttons:
            if b.owner_user_id != owner_user_id and b.team_id != team_id:
                continue
            if engine and b.engine != engine:
                continue
            out.append(b)
        out.sort(key=lambda b: (b.position, b.created_at))
        return out

    def put(self, button: CustomButton) -> None:
        with self._lock:
            buttons = self._load()
            buttons = [
                b
                for b in buttons
                if not (
                    b.owner_user_id == button.owner_user_id
                    and b.button_id == button.button_id
                )
            ]
            buttons.append(button)
            self._save(buttons)

    def get(self, owner_user_id: str, button_id: UUID) -> CustomButton:
        with self._lock:
            buttons = self._load()
        for b in buttons:
            if b.owner_user_id == owner_user_id and b.button_id == button_id:
                return b
        raise ButtonNotFound(str(button_id))

    def delete(self, owner_user_id: str, button_id: UUID) -> None:
        with self._lock:
            buttons = self._load()
            buttons = [
                b
                for b in buttons
                if not (b.owner_user_id == owner_user_id and b.button_id == button_id)
            ]
            self._save(buttons)

    def transact_update_positions(
        self,
        owner_user_id: str,
        updates: Sequence[ReorderEntry],
    ) -> None:
        if not updates:
            return
        with self._lock:
            buttons = self._load()
            index = {
                (b.owner_user_id, b.button_id): i
                for i, b in enumerate(buttons)
            }
            # Validate first.
            for u in updates:
                if (owner_user_id, u.button_id) not in index:
                    raise ButtonNotFound(str(u.button_id))
            now = datetime.now(timezone.utc)
            for u in updates:
                idx = index[(owner_user_id, u.button_id)]
                cur = buttons[idx]
                buttons[idx] = cur.model_copy(
                    update={"position": u.position, "updated_at": now}
                )
            self._save(buttons)
