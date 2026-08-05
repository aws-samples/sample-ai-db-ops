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

"""Strands hook that enforces human approval for Tier-3 database operations.

This is the framework half of the Tier-3 control; the decision logic it calls
lives in :mod:`src.hooks.tier3_gate`.

Why a hook and not a prompt instruction
---------------------------------------

The gate runs as a ``BeforeToolCallEvent`` callback on the Strands event bus,
which sits between the model's decision to call a tool and the tool actually
running. The model cannot see, reorder, or suppress it. A system-prompt rule
("never run Tier 3 without approval") is only a request to the model and is
defeated by any successful prompt injection, so it is not a security control.
This hook is.

Flow
----

1. Model proposes a Tier-3 tool call.
2. Hook raises a Strands interrupt carrying the tool name, the exact arguments,
   and a fingerprint over both. The agent loop stops; nothing is executed.
3. The caller (UI) shows the operator the pending operation and, on an explicit
   operator action, re-invokes with an ``approvals`` entry for that fingerprint.
4. Hook finds the matching decision, the interrupt resolves, and the tool runs
   only if the decision is ``APPLY``.

Because the approval is matched by fingerprint, an approval for one operation
cannot authorize a different one, and re-planning with different arguments
re-prompts rather than reusing the earlier consent.
"""

from __future__ import annotations

import logging
from typing import Any

from strands.hooks import (
    AfterToolCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from src.hooks.tier3_gate import (
    APPLY,
    INTERRUPT_NAME,
    approval_request,
    find_decision,
    operation_fingerprint,
    parse_approvals,
    requires_approval,
)

LOG = logging.getLogger(__name__)


class Tier3ApprovalHook(HookProvider):
    """Require an explicit operator ``APPLY`` before any Tier-3 tool executes.

    Args:
        approvals: The ``approvals`` list from the invocation payload, i.e.
            decisions the operator has already made for specific pending
            operations. Anything malformed is ignored (fail closed).
        user_id: Caller identity, recorded on audit lines.
    """

    def __init__(self, approvals: Any = None, user_id: str = "anonymous") -> None:
        self._approvals = parse_approvals(approvals)
        self._user_id = user_id or "anonymous"

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.gate_tier3)
        registry.add_callback(AfterToolCallEvent, self.audit_tier3)

    # ── Gate ────────────────────────────────────────────────────────────────

    def gate_tier3(self, event: BeforeToolCallEvent) -> None:
        """Halt a Tier-3 tool call until the operator has approved it."""
        tool_use = event.tool_use or {}
        tool_name = tool_use.get("name") or ""

        if not requires_approval(tool_name):
            return  # Tier 1/2 read-only tool — no gate.

        raw_input = tool_use.get("input")
        tool_input = raw_input if isinstance(raw_input, dict) else {}
        fingerprint = operation_fingerprint(tool_name, tool_input)
        decision = find_decision(self._approvals, tool_name, tool_input)

        if decision is None:
            LOG.info(
                "Tier-3 approval required: tool=%s fingerprint=%s user=%s",
                tool_name,
                fingerprint,
                self._user_id,
            )

        # With ``response=None`` this raises an interrupt and stops the agent
        # loop. On the follow-up invocation the operator's decision is supplied
        # preemptively, so the same call returns it instead of interrupting.
        response = event.interrupt(
            INTERRUPT_NAME,
            reason=approval_request(tool_name, tool_input),
            response=decision,
        )

        if not isinstance(response, str) or response.strip().upper() != APPLY:
            LOG.warning(
                "Tier-3 DENIED: tool=%s fingerprint=%s user=%s decision=%r",
                tool_name,
                fingerprint,
                self._user_id,
                response,
            )
            event.cancel_tool = (
                f"Operation '{tool_name}' was not approved by the operator "
                f"(decision: {response!r}). The tool was not executed."
            )
            return

        LOG.info(
            "Tier-3 APPROVED: tool=%s fingerprint=%s user=%s",
            tool_name,
            fingerprint,
            self._user_id,
        )

    # ── Audit ───────────────────────────────────────────────────────────────

    def audit_tier3(self, event: AfterToolCallEvent) -> None:
        """Record that an approved Tier-3 tool actually ran."""
        tool_use = event.tool_use or {}
        tool_name = tool_use.get("name") or ""
        if not requires_approval(tool_name):
            return
        raw_input = tool_use.get("input")
        tool_input = raw_input if isinstance(raw_input, dict) else {}
        LOG.info(
            "Tier-3 EXECUTED: tool=%s fingerprint=%s user=%s exception=%s",
            tool_name,
            operation_fingerprint(tool_name, tool_input),
            self._user_id,
            type(event.exception).__name__ if event.exception else None,
        )


def pending_approvals(result: Any) -> list[dict[str, Any]]:
    """Extract pending Tier-3 approval requests from an ``AgentResult``.

    Returns an empty list when the run finished without interrupting.
    """
    requests: list[dict[str, Any]] = []
    for interrupt in getattr(result, "interrupts", None) or []:
        if getattr(interrupt, "name", None) != INTERRUPT_NAME:
            continue
        reason = getattr(interrupt, "reason", None)
        if isinstance(reason, dict):
            requests.append({"interrupt_id": getattr(interrupt, "id", None), **reason})
    return requests
