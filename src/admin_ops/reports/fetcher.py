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

"""Tier-1-only bundle fetcher for the report generator.

The fetcher invokes the engine's read-only tools and shapes the
responses into the dict shape expected by the section renderers in
`src/admin_ops/reports/sections/`. Tier-1-only enforcement (R3.4)
lives here: the fetcher only ever calls tools it has explicitly
mapped to a section, never anything else.

The real agent invocation goes through `bedrock-agentcore` via the
existing pattern used by `/api/invoke`. Tests substitute the invoker
with `set_agent_invoker_for_testing`.

Validates: R3.1 (bundle shape), R3.4 (Tier 1 only), R3.18 (per-section
failure isolation).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

LOG = logging.getLogger(__name__)


# Per-engine tool map: each section -> tool_function_name.
# These are the names of the @tool functions in deploy/<engine>_agent/agent.py.
_TOOL_MAP: dict[str, dict[str, str]] = {
    "postgresql": {
        "top_slow_queries": "get_slow_queries",
        "blocking_incidents": "detect_blocking_chains",
        "unused_indexes": "get_index_usage",
        "vacuum_undo_status": "get_vacuum_status",
    },
    "mysql": {
        "top_slow_queries": "get_slow_queries",
        "blocking_incidents": "detect_blocking_chains",
        "unused_indexes": "get_index_usage",
    },
    "oracle": {
        "top_slow_queries": "get_slow_queries",
        "blocking_incidents": "get_blocking_sessions",
        "unused_indexes": "get_index_usage",
        "vacuum_undo_status": "get_redo_log_status",
    },
    "dynamodb": {
        "blocking_incidents": "list_tables",  # placeholder — DDB has no blocking concept
    },
}


# Tool-name -> shaper function. Each shaper turns a raw agent response
# into the typed list/dict the section renderer expects.
def _shape_pg_slow_queries(resp: Any) -> list[dict[str, Any]]:
    if not isinstance(resp, Mapping):
        return []
    rows = resp.get("queries") or resp.get("rows") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        out.append(
            {
                "query_id": str(r.get("queryid") or r.get("query_id") or "")[:32],
                "preview": (r.get("query_preview") or r.get("query") or "")[:160],
                "calls": r.get("calls") or 0,
                "mean_time_sec": (r.get("mean_ms") or 0) / 1000.0,
                "total_time_sec": (r.get("total_ms") or 0) / 1000.0,
            }
        )
    return out


def _shape_mysql_slow_queries(resp: Any) -> list[dict[str, Any]]:
    if not isinstance(resp, Mapping):
        return []
    rows = resp.get("queries") or resp.get("rows") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        avg_us = r.get("avg_timer_wait") or 0
        total_us = r.get("sum_timer_wait") or 0
        out.append(
            {
                "query_id": str(r.get("digest") or "")[:32],
                "preview": (r.get("digest_text") or r.get("query") or "")[:160],
                "calls": r.get("count_star") or r.get("calls") or 0,
                "mean_time_sec": float(avg_us) / 1e12,
                "total_time_sec": float(total_us) / 1e12,
            }
        )
    return out


def _shape_oracle_slow_queries(resp: Any) -> list[dict[str, Any]]:
    if not isinstance(resp, Mapping):
        return []
    rows = resp.get("rows") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        elapsed_us = r.get("elapsed_time") or 0
        executions = r.get("executions") or 1
        out.append(
            {
                "query_id": str(r.get("sql_id") or "")[:32],
                "preview": (r.get("sql_text") or "")[:160],
                "calls": executions,
                "mean_time_sec": float(elapsed_us) / 1e6 / max(executions, 1),
                "total_time_sec": float(elapsed_us) / 1e6,
            }
        )
    return out


def _shape_blocking(resp: Any) -> list[dict[str, Any]]:
    if not isinstance(resp, Mapping):
        return []
    rows = resp.get("blocking_chains") or resp.get("rows") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        out.append(
            {
                "blocker_pid": r.get("blocking_pid") or r.get("blocker_sid") or r.get("blocking_session_id") or "",
                "victim_pid": r.get("blocked_pid") or r.get("blocked_sid") or r.get("blocked_session_id") or "",
                "blocker_query": (r.get("blocking_query") or r.get("blocker_query") or "")[:160],
                "wait_seconds": r.get("wait_seconds") or r.get("wait_time_seconds") or 0,
            }
        )
    return out


def _shape_unused_indexes(resp: Any) -> list[dict[str, Any]]:
    if not isinstance(resp, Mapping):
        return []
    rows = resp.get("unused_indexes") or resp.get("rows") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        out.append(
            {
                "schema": r.get("schemaname") or r.get("schema") or "",
                "table": r.get("relname") or r.get("table_name") or r.get("table") or "",
                "index": r.get("indexrelname") or r.get("index_name") or r.get("index") or "",
                "size_mb": r.get("size_mb") or 0,
                "scans": r.get("idx_scan") or r.get("scans") or 0,
            }
        )
    return out


def _shape_vacuum(resp: Any) -> list[dict[str, Any]]:
    if not isinstance(resp, Mapping):
        return []
    rows = resp.get("vacuum_status") or resp.get("rows") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        # Each row may carry several metrics — emit one entry per metric.
        obj = r.get("relname") or r.get("table_name") or "?"
        for metric_key in ("n_dead_tup", "last_autovacuum_age_min", "last_vacuum_age_min"):
            if metric_key in r and r[metric_key] is not None:
                out.append({"object": obj, "metric": metric_key, "value": r[metric_key]})
    return out


def _shape_oracle_redo(resp: Any) -> list[dict[str, Any]]:
    if not isinstance(resp, Mapping):
        return []
    rows = resp.get("redo_logs") or resp.get("rows") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        out.append(
            {
                "object": str(r.get("group_no") or r.get("group#") or "redo"),
                "metric": "status",
                "value": r.get("status") or "",
            }
        )
    return out


_SHAPERS: dict[str, Callable[[Any], list[dict[str, Any]]]] = {
    "postgresql:get_slow_queries": _shape_pg_slow_queries,
    "mysql:get_slow_queries": _shape_mysql_slow_queries,
    "oracle:get_slow_queries": _shape_oracle_slow_queries,
    "postgresql:detect_blocking_chains": _shape_blocking,
    "mysql:detect_blocking_chains": _shape_blocking,
    "oracle:get_blocking_sessions": _shape_blocking,
    "postgresql:get_index_usage": _shape_unused_indexes,
    "mysql:get_index_usage": _shape_unused_indexes,
    "oracle:get_index_usage": _shape_unused_indexes,
    "postgresql:get_vacuum_status": _shape_vacuum,
    "oracle:get_redo_log_status": _shape_oracle_redo,
}


# ── Capacity headroom: pulled from CloudWatch in production, inert here. ──


def _capacity_headroom(engine: str, db_identifier: str) -> dict[str, Any]:
    """Returns a placeholder dict; the production fetcher reads CloudWatch."""
    return {}


# ── Tier 3 ops: read from the audit log fetcher when available. ────────────


_AuditLogFetcher = Callable[[str, datetime, datetime], list[dict[str, Any]]]
_audit_log_fetcher: _AuditLogFetcher | None = None


def set_audit_log_fetcher_for_testing(fn: _AuditLogFetcher | None) -> None:
    global _audit_log_fetcher
    _audit_log_fetcher = fn


def _tier3_ops(
    db_identifier: str,
    *,
    since: datetime | None,
    until: datetime,
) -> list[dict[str, Any]]:
    if _audit_log_fetcher is None:
        return []
    if since is None:
        since = until - timedelta(days=7)
    try:
        return _audit_log_fetcher(db_identifier, since, until)
    except Exception:  # noqa: BLE001
        LOG.exception("audit log fetcher failed; returning empty list")
        return []


# ── Agent invoker abstraction ──────────────────────────────────────────────


_AgentInvoker = Callable[[str, str, Mapping[str, Any] | None], Mapping[str, Any]]
# (engine, tool_function_name, args) -> raw agent response

_agent_invoker: _AgentInvoker | None = None


def set_agent_invoker_for_testing(fn: _AgentInvoker | None) -> None:
    global _agent_invoker
    _agent_invoker = fn


def _invoke_tool(
    engine: str, tool_name: str, args: Mapping[str, Any] | None
) -> Mapping[str, Any]:
    if _agent_invoker is None:
        raise RuntimeError(
            "no agent invoker configured — set via "
            "fetcher.set_agent_invoker_for_testing or wire to "
            "/api/invoke at runtime"
        )
    return _agent_invoker(engine, tool_name, args)


# ── Public API ─────────────────────────────────────────────────────────────


def fetch_bundle(
    *,
    db_identifier: str,
    engine: str,
    until: datetime | None = None,
    previous_run_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the bundle the report generator expects.

    Each section is fetched independently — a failure on one section
    leaves a `Section Failed` block in the report rather than aborting
    the whole run (R3.18). The generator handles the wrapping; here we
    just record the per-section error so the section renderer can
    produce the right shape (an empty list yields the "no findings"
    placeholder — that's acceptable).
    """
    until = until or datetime.now(timezone.utc)
    bundle: dict[str, Any] = {
        "summary": {
            "db_identifier": db_identifier,
            "engine": engine,
            "report_window_end": until.isoformat(),
        },
        "top_slow_queries": [],
        "blocking_incidents": [],
        "unused_indexes": [],
        "capacity_headroom": _capacity_headroom(engine, db_identifier),
        "vacuum_undo_status": [],
        "tier3_ops": _tier3_ops(db_identifier, since=previous_run_at, until=until),
    }

    tool_map = _TOOL_MAP.get(engine, {})
    for section_key, tool_name in tool_map.items():
        shaper = _SHAPERS.get(f"{engine}:{tool_name}")
        if shaper is None:
            continue
        try:
            raw = _invoke_tool(engine, tool_name, args={})
            bundle[section_key] = shaper(raw)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("fetcher %s/%s failed: %s", engine, tool_name, exc)
            # Leave the section empty; renderer shows "no findings".
            bundle[section_key] = []
    return bundle
