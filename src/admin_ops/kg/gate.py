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

"""Fail-closed gating resolution for the DBA knowledge graph (R1.7, R4.3-R4.7, R10.4).

The DBA View is gated by a single config key,
``config.yaml::knowledge_graph.gating_state``, which must be one of three
literals:

* ``pending`` — the capability is provisioned but not yet turned on; routes
  serve only the static schema and ``health: pending``. No ingest, no traversal.
* ``approved`` — the capability is live; ingestion and traversal run.
* ``not_approved`` — the capability is intentionally withheld; routes return a
  not-available response (never a fault-implying error).

Any *other* value, or a missing key, is treated as a fault and raises
:class:`GateUnavailable` so every caller fails closed (R4.6, R10.4): a
misconfiguration must never accidentally expose graph data.

This module reuses the platform's existing
``src/admin_ops/config/require.py::require_config`` so the fail-closed behavior
(missing/empty config -> error) is identical to the rest of admin-ops. No AWS
import is needed; the gate is a pure config read.
"""

from __future__ import annotations

from typing import Literal, get_args

from src.admin_ops.config.require import MissingConfigError, require_config

GatingState = Literal["pending", "approved", "not_approved"]

# The closed set of valid gating states, derived from the Literal so the two
# can never drift apart.
_VALID_STATES: frozenset[str] = frozenset(get_args(GatingState))


class GateUnavailable(RuntimeError):
    """``gating_state`` is missing or invalid -> fail closed (R4.6, R10.4).

    Carries the offending value (or ``None`` when the key is absent) so the
    audit/observability layer can name exactly what was wrong without leaking
    anything else.
    """

    def __init__(self, *, found: object | None = None, reason: str) -> None:
        self.found = found
        self.reason = reason
        super().__init__(f"knowledge_graph.gating_state unavailable: {reason}")


def gating_state() -> GatingState:
    """Return the configured gating state, or raise :class:`GateUnavailable`.

    Reads ``config.yaml::knowledge_graph.gating_state`` via
    ``require_config``. A missing/empty key (``MissingConfigError``) or any
    value outside ``{pending, approved, not_approved}`` raises
    :class:`GateUnavailable` so callers fail closed (R4.6, R10.4).
    """
    try:
        raw = require_config("knowledge_graph", "gating_state")
    except MissingConfigError as exc:
        raise GateUnavailable(
            found=None, reason="knowledge_graph.gating_state is missing or empty"
        ) from exc

    if not isinstance(raw, str) or raw not in _VALID_STATES:
        raise GateUnavailable(
            found=raw,
            reason=(
                "gating_state must be one of "
                f"{sorted(_VALID_STATES)}; the configured value is not recognized"
            ),
        )
    # mypy: raw is a str known to be in the valid set, hence a GatingState.
    return raw  # type: ignore[return-value]


def require_approved() -> None:
    """Raise unless the gating state is exactly ``approved`` (R4.3).

    Used by ingestion and traversal entry points: ingestion runs and the graph
    is served only while ``approved``. ``pending`` / ``not_approved`` raise
    :class:`GateUnavailable` with a non-fault reason so the caller can surface
    an intentional-gate response rather than an error; a missing/invalid value
    also raises (fail closed).
    """
    state = gating_state()
    if state != "approved":
        raise GateUnavailable(
            found=state,
            reason=f"gating_state is {state!r}; approved is required",
        )
