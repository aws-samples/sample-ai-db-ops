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

"""Unit tests for the KG access-audit wrapper (R9.2, R9.5).

``emit_access`` emits exactly one entry carrying the required fields; an
emitter failure raises ``AuditEmitFailed`` so the caller fails the request with
no graph data returned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

import pytest

from src.admin_ops.kg import audit
from src.admin_ops.kg.audit import AuditEmitFailed, emit_access


@pytest.fixture(autouse=True)
def _restore_emitter() -> None:
    yield
    audit.set_audit_emitter_for_testing(None)


def test_emit_access_emits_one_entry_with_required_fields() -> None:
    captured: list[Mapping[str, Any]] = []
    audit.set_audit_emitter_for_testing(captured.append)

    emit_access(user_id="dba-user", route="dba_graph", focus="Database:database-test")

    assert len(captured) == 1
    entry = captured[0]
    assert entry["op"] == "kg_access"
    assert entry["user"] == "dba-user"
    assert entry["route"] == "dba_graph"
    assert entry["focus"] == "Database:database-test"
    # timestamp is UTC ISO-8601 and parseable.
    parsed = datetime.fromisoformat(entry["timestamp"])
    assert parsed.tzinfo is not None


def test_emit_access_omits_focus_when_absent() -> None:
    captured: list[Mapping[str, Any]] = []
    audit.set_audit_emitter_for_testing(captured.append)

    emit_access(user_id="dba-user", route="dba_timeline")

    assert len(captured) == 1
    assert "focus" not in captured[0]


def test_emit_access_emits_exactly_once_per_call() -> None:
    calls = {"n": 0}

    def _count(_entry: Mapping[str, Any]) -> None:
        calls["n"] += 1

    audit.set_audit_emitter_for_testing(_count)
    emit_access(user_id="u", route="dba_unticketed")
    assert calls["n"] == 1


def test_emit_failure_raises_audit_emit_failed() -> None:
    def _boom(_entry: Mapping[str, Any]) -> None:
        raise RuntimeError("audit sink unreachable")

    audit.set_audit_emitter_for_testing(_boom)
    with pytest.raises(AuditEmitFailed):
        emit_access(user_id="u", route="dba_graph", focus="Principal:appuser@appdb")
