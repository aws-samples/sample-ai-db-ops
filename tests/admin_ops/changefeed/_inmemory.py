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

"""In-memory ChangeFeedBackend for tests (no AWS)."""

from __future__ import annotations

from src.admin_ops.changefeed.change_event import ChangeEvent
from src.admin_ops.changefeed.store import _ChangeFeedBackend


class InMemoryChangeFeedBackend(_ChangeFeedBackend):
    def __init__(self) -> None:
        # Keyed by event_id; insertion order preserved (Python 3.7+ dict).
        self._records: dict[str, ChangeEvent] = {}

    def put_event(self, event: ChangeEvent) -> bool:
        if event.event_id in self._records:
            return False
        self._records[event.event_id] = event
        return True

    def all_events(self) -> list[ChangeEvent]:
        return list(self._records.values())
