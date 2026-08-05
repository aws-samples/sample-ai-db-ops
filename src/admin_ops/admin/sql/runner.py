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

"""Tier-aware SQL execution.

Workflow:
1. Classify the statement (`classifier.classify`).
2. If `tier_1_read` and the engine has a live connection adapter → run
   directly via `execute_with_params` and return rows.
3. If `tier_2_advise` → forward the body to the engine's agent as a
   prompt. The agent decides whether to act.
4. If `tier_3_act` → require the literal `APPLY` confirmation token
   (R2.15), then forward through the agent's `execute_sql` tool, where
   `Tier3ApprovalHook` independently gates execution on the agent side.

This module owns the audit emission boundary — every call lands one
entry through the AuditHook surface (R7.5). The hook itself is
unchanged; we just call it.

Validates: R2.10–R2.16, R2.19, R7.3, R7.5, R7.9.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from src.admin_ops.admin.sql.classifier import Classification, classify
from src.admin_ops.errors import safe_error

LOG = logging.getLogger(__name__)

# Sensitivity of this logger's destination.
#
# The two audiences are split deliberately: audit records and raised errors carry
# the exception *type* only (via ``safe_error``), while ``LOG.exception`` keeps
# the full traceback. That is not an oversight — without it nobody can diagnose a
# failed statement — but it does mean this log inherits the sensitivity of the
# SQL that flows through the runner. A traceback here can contain the submitted
# statement and, from some drivers, bound parameter values.
#
# Treat the destination accordingly: restrict who can read it, apply the same
# retention you would give the underlying tables, and do not ship it to a
# general-purpose or third-party log sink without re-reviewing that decision. If
# your environment cannot meet that, lower this to ``LOG.error("... (%s)",
# safe_error(exc))`` and accept the loss of diagnostic detail — but change it
# here rather than at each call site, so the choice stays visible.


class TierThreeRequiresApply(PermissionError):
    """Raised when caller invokes a Tier 3 statement without typing APPLY."""


class AgentInvocationFailed(RuntimeError):
    """Raised when the underlying agent call fails or times out."""


@dataclass
class RunResult:
    classification: Classification
    rows: list[dict[str, Any]] | None = None
    rowcount: int | None = None
    forwarded_to_agent: bool = False
    apply_token_required: bool = False


# ── Hook injection points (decoupled from concrete adapter packages) ────


_AuditEmit = Callable[[Mapping[str, Any]], None]
_AgentInvoke = Callable[[str, str, str], Mapping[str, Any]]
# (engine, body, user_id) -> response dict
_DirectExec = Callable[[str, str, Mapping[str, Any] | None], list[dict[str, Any]] | int]
# (engine, sql, params) -> rows or rowcount


def _default_audit_emit(entry: Mapping[str, Any]) -> None:
    LOG.info("audit %s", dict(entry))


def _default_agent_invoke(engine: str, body: str, user_id: str) -> Mapping[str, Any]:
    raise AgentInvocationFailed(
        "no agent_invoke configured — set via runner.set_agent_invoker_for_testing"
    )


def _default_direct_exec(
    engine: str, sql: str, params: Mapping[str, Any] | None
) -> list[dict[str, Any]] | int:
    raise AgentInvocationFailed(
        "no direct_exec configured — set via runner.set_direct_exec_for_testing"
    )


_audit_emit: _AuditEmit = _default_audit_emit
_agent_invoke: _AgentInvoke = _default_agent_invoke
_direct_exec: _DirectExec = _default_direct_exec


def set_audit_emitter_for_testing(fn: _AuditEmit | None) -> None:
    global _audit_emit
    _audit_emit = fn or _default_audit_emit


def set_agent_invoker_for_testing(fn: _AgentInvoke | None) -> None:
    global _agent_invoke
    _agent_invoke = fn or _default_agent_invoke


def set_direct_exec_for_testing(fn: _DirectExec | None) -> None:
    global _direct_exec
    _direct_exec = fn or _default_direct_exec


# ─── Public API ─────────────────────────────────────────────────────────────


def run(
    *,
    engine: str,
    body: str,
    user_id: str,
    params: Mapping[str, Any] | None = None,
    apply_token: str | None = None,
) -> RunResult:
    """Classify, then execute or forward; emit an audit entry on every path."""
    cls = classify(engine, body)
    base_audit = {
        "op": "sql_run",
        "user": user_id,
        "engine": engine,
        "tier": cls.tier,
        "leading_keyword": cls.leading_keyword,
        "reason": cls.reason,
    }

    if cls.tier == "tier_1_read":
        try:
            result = _direct_exec(engine, body, params)
        except Exception as exc:  # noqa: BLE001
            # Type only: driver messages embed the failing statement and can
            # embed bound values. Full detail goes to the operator log.
            LOG.exception("direct execution failed for engine=%s", engine)
            _audit_emit({**base_audit, "outcome": "exec_failed", "error": safe_error(exc)})
            raise
        if isinstance(result, int):
            _audit_emit({**base_audit, "outcome": "ok", "rowcount": result})
            return RunResult(classification=cls, rowcount=result)
        _audit_emit({**base_audit, "outcome": "ok", "row_count_returned": len(result)})
        return RunResult(classification=cls, rows=result)

    if cls.tier == "tier_3_act":
        # "APPLY" is a human confirmation token, not a credential.
        if apply_token != "APPLY":  # nosec B105
            _audit_emit({**base_audit, "outcome": "apply_token_missing"})
            raise TierThreeRequiresApply(
                "Tier 3 statement requires apply_token == 'APPLY'"
            )
        # Forward to the agent's execute_sql tool. Tier3ApprovalHook gates the
        # call there, so the agent-side approval is enforced independently of
        # this apply_token check.
        try:
            response = _agent_invoke(engine, body, user_id)
        except Exception as exc:  # noqa: BLE001
            # Type only in the audit record and in the raised error: the agent
            # payload echoes the submitted statement.
            LOG.exception("agent invocation failed for engine=%s", engine)
            _audit_emit({**base_audit, "outcome": "agent_failed", "error": safe_error(exc)})
            raise AgentInvocationFailed(safe_error(exc)) from exc
        _audit_emit({**base_audit, "outcome": "agent_ok"})
        return RunResult(
            classification=cls,
            forwarded_to_agent=True,
            rows=[dict(response)] if isinstance(response, Mapping) else None,
        )

    # tier_2_advise — forward as prompt.
    try:
        response = _agent_invoke(engine, body, user_id)
    except Exception as exc:  # noqa: BLE001
        # Identical treatment to the tier_3 path above, and for the identical
        # reason: this is the same _agent_invoke call, so the failure payload can
        # echo the submitted statement. The audit record and the raised error
        # carry the exception type only; the traceback goes to the operator log.
        LOG.exception("agent invocation failed for engine=%s", engine)
        _audit_emit({**base_audit, "outcome": "agent_failed", "error": safe_error(exc)})
        raise AgentInvocationFailed(safe_error(exc)) from exc
    _audit_emit({**base_audit, "outcome": "agent_ok"})
    return RunResult(
        classification=cls,
        forwarded_to_agent=True,
        rows=[dict(response)] if isinstance(response, Mapping) else None,
    )
