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

"""Local-dev backend for the change feed.

Activated when ADMIN_DEV_BYPASS=1 -- persists change events to a single
JSON file under the user's home directory so the demo survives Next.js
dev-server restarts. Not imported on production paths; `_get_backend`
in `store.py` only swaps it in when the env var is set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from src.admin_ops.changefeed.change_event import ChangeEvent
from src.admin_ops.changefeed.store import _ChangeFeedBackend


def _state_file() -> Path:
    override = os.environ.get("CHANGEFEED_DEV_STATE_FILE")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    target = base / "dbops" / "dev_changefeed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


class JsonFileChangeFeedBackend(_ChangeFeedBackend):
    """JSON-file-backed backend used only when ADMIN_DEV_BYPASS=1."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _state_file()
        self._lock = RLock()

    def _load(self) -> dict[str, ChangeEvent]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, list):
            return {}
        out: dict[str, ChangeEvent] = {}
        for item in raw:
            try:
                ev = ChangeEvent.model_validate(item)
            except Exception:
                continue
            out[ev.event_id] = ev
        return out

    def _save(self, records: dict[str, ChangeEvent]) -> None:
        payload = [e.model_dump(mode="json") for e in records.values()]
        self._path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

    def put_event(self, event: ChangeEvent) -> bool:
        with self._lock:
            records = self._load()
            if event.event_id in records:
                return False
            records[event.event_id] = event
            self._save(records)
            return True

    def all_events(self) -> list[ChangeEvent]:
        with self._lock:
            return list(self._load().values())
