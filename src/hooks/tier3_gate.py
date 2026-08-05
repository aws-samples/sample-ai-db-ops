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

"""Tier-3 approval gate — pure decision logic.

This module holds the *decision* half of the Tier-3 human-approval control.
It deliberately has no dependency on ``strands`` (or any AWS SDK) so it can be
unit-tested in isolation; the framework wiring lives in
``src/hooks/tier3_approval.py``.

Design notes
------------

**Fail closed.** Tools are classified by an explicit allowlist of *read-only*
(Tier 1/2) tools. Anything not on that allowlist is treated as Tier 3 and
requires human approval. A denylist of mutating tools would silently fail open
the moment a new mutating tool is added, so the polarity is inverted here on
purpose: adding a tool without updating this module produces an approval
prompt (an inconvenience), never a silent execution (a vulnerability).

**Approvals are bound to one exact operation.** An approval carries a
fingerprint over the tool name *and* its arguments. A stale or replayed
``APPLY`` therefore cannot authorize a different operation, and it cannot
authorize the same tool with different arguments. This matters because the
model re-plans on the follow-up invocation: if it proposes anything other than
what the operator saw and approved, the fingerprint will not match and the
gate re-prompts.

**Approvals never originate from the model.** Decisions are read from the
invocation payload, which is constructed by the calling application (the UI)
from an explicit operator action. Text produced by the model, or content read
out of a database, cannot introduce an approval into that channel.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# Name used for the Strands interrupt raised by the gate.
INTERRUPT_NAME = "dbops_tier3_approval"

# Decisions understood by the gate. Matching is case-insensitive after
# stripping surrounding whitespace; everything else is treated as a denial.
APPLY = "APPLY"
DENY = "DENY"

# ── Read-only (Tier 1/2) tool allowlist ─────────────────────────────────────
#
# Every entry was verified against its implementation to contain no mutating
# SQL and no mutating AWS API call. Tools absent from this set require
# approval. Keep this sorted; it is asserted against the deployed tool
# inventory by tests/admin_ops/safety/test_tier3_inventory.py.
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "check_txid_wraparound",
        "describe_table",
        "detect_blocking_chains",
        "get_active_sessions",
        "get_ash_top_sql",
        "get_autoscaling_status",
        "get_blocking_sessions",
        "get_cloudwatch_metrics",
        "get_cluster_info",
        "get_connected_clients",
        "get_connections_summary",
        "get_database_size",
        "get_gsi_status",
        "get_hit_ratio",
        "get_index_usage",
        "get_innodb_status",
        "get_instance_details",
        "get_masking_policies",
        "get_memory_stats",
        "get_processlist",
        "get_rds_instance_details",
        "get_redo_log_status",
        "get_replication_status",
        "get_slow_commands",
        "get_slow_queries",
        "get_sql_plan",
        "get_table_bloat",
        "get_table_metrics",
        "get_table_ttl",
        "get_throttled_requests",
        "get_user_profile",
        "get_vacuum_status",
        "get_wait_events",
        "list_backups",
        "list_databases",
        "list_dev_databases",
        "list_schemas",
        "list_tables",
        "list_tablespaces",
        "query_table",
        "recommend_eviction_policy",
        "recommend_index",
        "scan_sample_items",
    }
)


def requires_approval(tool_name: str) -> bool:
    """Return True when ``tool_name`` may not run without human approval.

    Fail-closed: an unknown, empty, or non-string tool name requires approval.
    """
    if not isinstance(tool_name, str) or not tool_name.strip():
        return True
    return tool_name.strip() not in READ_ONLY_TOOLS


def operation_fingerprint(tool_name: str, tool_input: Mapping[str, Any] | None) -> str:
    """Return a stable SHA-256 fingerprint binding a tool to its arguments.

    The fingerprint is what makes an approval single-purpose: it covers the
    tool name and the full argument map, so an ``APPLY`` issued for one
    operation cannot be replayed against another.
    """
    payload = {
        "tool": (tool_name or "").strip(),
        "input": _canonical(tool_input if isinstance(tool_input, Mapping) else {}),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> Any:
    """Recursively normalize a value into something JSON-canonicalizable."""
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass(frozen=True)
class Approval:
    """One operator decision about one specific pending operation."""

    tool: str
    fingerprint: str
    decision: str

    def approves(self) -> bool:
        return self.decision.strip().upper() == APPLY


def parse_approvals(raw: Any) -> tuple[Approval, ...]:
    """Parse the ``approvals`` element of an invocation payload.

    Malformed entries are dropped rather than raising: a caller that sends
    garbage gets no approval (fail closed), not an agent crash.
    """
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, Mapping)):
        return ()
    parsed: list[Approval] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        tool = item.get("tool")
        fingerprint = item.get("fingerprint")
        decision = item.get("decision")
        if not isinstance(tool, str) or not isinstance(fingerprint, str):
            continue
        if not isinstance(decision, str) or not decision.strip():
            continue
        parsed.append(
            Approval(tool=tool.strip(), fingerprint=fingerprint.strip(), decision=decision.strip())
        )
    return tuple(parsed)


def find_decision(
    approvals: Iterable[Approval],
    tool_name: str,
    tool_input: Mapping[str, Any] | None,
) -> str | None:
    """Return the operator decision for this exact operation, else ``None``.

    ``None`` means "no decision supplied" — the caller should interrupt and ask.
    Both the tool name and the argument fingerprint must match, so approvals
    are neither transferable between tools nor replayable with new arguments.
    """
    expected = operation_fingerprint(tool_name, tool_input)
    for approval in approvals:
        if approval.tool == (tool_name or "").strip() and _constant_time_eq(
            approval.fingerprint, expected
        ):
            return approval.decision
    return None


def _constant_time_eq(left: str, right: str) -> bool:
    """Compare two hex digests without leaking length/content via timing."""
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def approval_request(tool_name: str, tool_input: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build the operator-facing description of a pending Tier-3 operation.

    Returned as the interrupt ``reason`` and surfaced by the UI so the operator
    approves a concrete, fully-specified action rather than a vague intent.
    """
    fingerprint = operation_fingerprint(tool_name, tool_input)
    return {
        "kind": "tier3_approval_required",
        "tool": tool_name,
        "input": _canonical(tool_input if isinstance(tool_input, Mapping) else {}),
        "fingerprint": fingerprint,
        "message": (
            f"Tier-3 operation '{tool_name}' requires explicit approval. "
            f"Review the parameters, then reply {APPLY} to run it or {DENY} to cancel."
        ),
        "apply_token": APPLY,
        "deny_token": DENY,
    }
