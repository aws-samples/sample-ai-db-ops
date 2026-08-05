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

"""Shared Change_Event model, parser, and pretty printer (R4.2, R4.7, R4.8).

Resolved spec inconsistency
---------------------------
requirements.md R4.2 describes ``event_id`` as a "UUID v4", but the design
document, R4.6 (dedup), and correctness property P10 (dedup idempotence) all
require a *deterministic* identifier: equal logical inputs must produce equal
ids so duplicate writes converge to a single record. A random UUID v4 cannot
satisfy that. We therefore follow the DESIGN: ``event_id`` is a deterministic
SHA-256 digest (truncated to 32 hex chars) of the normalized identity tuple
``(source, actor, int(timestamp), resource_id)`` via :func:`make_event_id`.

The model serializes ``timestamp`` as ``.isoformat()`` and forbids unknown
fields (``extra="forbid"``). ``print_event`` emits canonical JSON with sorted
keys so the round-trip property ``parse(print_event(e)) == e`` (P9, R4.8)
holds deterministically.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

Source = Literal["git", "cloudtrail", "agent", "database"]
Engine = Literal["postgresql", "mysql", "oracle", "dynamodb"]
Severity = Literal["low", "medium", "high", "critical"]


class ChangeEvent(BaseModel):
    """One normalized change to a SQL template or tracked DB infrastructure."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=64)  # sha256 hex (see module docstring)
    source: Source
    actor: str = Field(min_length=1, max_length=128)
    timestamp: datetime  # UTC, ISO-8601
    engine: Engine | None = None
    resource_id: str = Field(min_length=1, max_length=256)
    severity: Severity
    summary: str = Field(min_length=1, max_length=512)
    details_url: str = Field(min_length=1, max_length=2048)
    raw_payload_ref: str = Field(min_length=1, max_length=512)

    @field_serializer("timestamp", when_used="json")
    def _serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat()


def make_event_id(source: str, actor: str, ts: datetime, resource_id: str) -> str:
    """Return a deterministic 32-hex-char id for the identity tuple.

    Equal inputs yield equal ids (R4.6, P10). Truncated to 32 chars per the
    design doc.
    """
    s = f"{source}|{actor}|{int(ts.timestamp())}|{resource_id}"
    return hashlib.sha256(s.encode()).hexdigest()[:32]


def parse(payload: dict | str) -> ChangeEvent:
    """Parse a JSON string or dict into a validated :class:`ChangeEvent`.

    Raises ``pydantic.ValidationError`` (or ``json.JSONDecodeError`` for
    malformed JSON strings) on invalid input.
    """
    if isinstance(payload, str):
        data = json.loads(payload)
    elif isinstance(payload, dict):
        data = payload
    else:  # pragma: no cover - defensive guard
        raise TypeError(f"parse expects dict or str, got {type(payload).__name__}")
    return ChangeEvent.model_validate(data)


def print_event(e: ChangeEvent) -> str:
    """Serialize a :class:`ChangeEvent` to canonical JSON (sorted keys).

    Named ``print_event`` rather than ``print`` to avoid shadowing the
    builtin. ``parse(print_event(e)) == e`` holds (P9, R4.8).
    """
    return json.dumps(e.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
