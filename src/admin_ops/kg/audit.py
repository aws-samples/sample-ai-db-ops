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

"""Access audit for the DBA knowledge graph (R9.2, R9.5).

Every DBA View route emits exactly one audit entry per access through
:func:`emit_access`, recording the requesting ``user_id``, the route/query id,
the focus ``node_id`` (when the request targets one), and a UTC timestamp.

The emission boundary mirrors ``src/admin_ops/admin/sql/runner.py``: a single
module-level emitter callable that defaults to structured logging and is
swappable for tests via :func:`set_audit_emitter_for_testing`. The concrete
``AuditHook`` surface used by the rest of admin-ops is unchanged; this module
only formats the KG access entry and calls it.

Fail-closed contract (R9.5): if the emitter raises, :func:`emit_access`
propagates :class:`AuditEmitFailed`. The caller (each route) MUST treat that as
a hard failure and return **no** graph data — auditing an access is a
precondition for serving it, not a best-effort side effect.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

LOG = logging.getLogger(__name__)

# (entry) -> None. Mirrors runner._AuditEmit so a deployment can wire both
# emission points to the same concrete AuditHook.
_AuditEmit = Callable[[Mapping[str, Any]], None]


class AuditEmitFailed(RuntimeError):
    """The audit emitter raised; the request MUST fail with no data (R9.5)."""


def _default_audit_emit(entry: Mapping[str, Any]) -> None:
    LOG.info("kg_audit %s", dict(entry))


_audit_emit: _AuditEmit = _default_audit_emit


def set_audit_emitter_for_testing(fn: _AuditEmit | None) -> None:
    """Swap the audit emitter (tests). ``None`` restores the default."""
    global _audit_emit
    _audit_emit = fn or _default_audit_emit


def emit_access(
    user_id: str,
    route: str,
    focus: str | None = None,
) -> None:
    """Emit one audit entry for a DBA View access (R9.2).

    The entry always carries ``op="kg_access"``, the requesting ``user_id``,
    the ``route`` (or query id), and a UTC ISO-8601 ``timestamp``; ``focus`` is
    included only when the request targets a specific node. Exactly one entry
    is emitted per call.

    Raises :class:`AuditEmitFailed` if the underlying emitter raises, so the
    caller can fail the request and return no graph data (R9.5).
    """
    entry: dict[str, Any] = {
        "op": "kg_access",
        "user": user_id,
        "route": route,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if focus is not None:
        entry["focus"] = focus
    try:
        _audit_emit(entry)
    except Exception as exc:  # noqa: BLE001 - any emitter failure fails closed
        raise AuditEmitFailed(str(exc)) from exc
