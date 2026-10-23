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

"""Drift guards tying the Tier-3 allowlist to the deployed agents.

The gate's correctness depends on ``READ_ONLY_TOOLS`` genuinely containing only
read-only tools. These tests re-derive that fact from the agent sources, so the
combination of "someone adds a mutating tool" and "someone adds it to the
allowlist" fails the build instead of shipping a bypass.

They also assert the wiring itself: every agent constructs its ``Agent`` with
the hook, and no agent re-introduces ``BYPASS_TOOL_CONSENT``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.hooks.tier3_gate import READ_ONLY_TOOLS, requires_approval

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_FILES = sorted(REPO_ROOT.glob("deploy/*_agent/agent.py"))
TOOL_SOURCE_FILES = list(AGENT_FILES)

# Statements and API calls that mutate state, cause disruption, or move data
# out of the database.
_MUTATING_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|REINDEX"
    r"|MERGE|KILL|GATHER_TABLE_STATS)\b",
    re.I,
)
_MUTATING_API = re.compile(
    r"\.(put_item|update_item|delete_item|batch_write_item|create_table"
    r"|update_table|delete_table|create_backup|restore_table"
    r"|export_table_to_point_in_time|update_time_to_live|modify_db_instance"
    r"|modify_db_cluster|create_db_instance|create_db_snapshot"
    r"|create_db_cluster_snapshot|copy_db_cluster_snapshot"
    r"|restore_db_cluster_from_snapshot|register_scalable_target"
    r"|put_scaling_policy|deregister_scalable_target|delete_scaling_policy"
    r"|update_contributor_insights|client_kill|config_set)\(",
    re.I,
)

# Tools that mention a mutating keyword only inside a read-only query — for
# example selecting ``last_vacuum`` from ``pg_stat_user_tables``, or reading
# ``pg_indexes`` to recommend an index. Each was read and confirmed to issue
# SELECT statements only. Anything not listed here must be genuinely clean.
_VERIFIED_READ_ONLY_DESPITE_KEYWORD = {
    "check_txid_wraparound",  # SELECT ... FROM pg_database
    "get_vacuum_status",  # SELECT ... FROM pg_stat_user_tables
    "recommend_index",  # SELECTs over catalog/statistics views
}


def _tool_bodies() -> dict[str, list[tuple[str, str]]]:
    """Map tool name -> [(agent, source of the decorated function)]."""
    bodies: dict[str, list[tuple[str, str]]] = {}
    for path in TOOL_SOURCE_FILES:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef):
                continue
            decorated = any(
                (getattr(d, "id", None) or getattr(getattr(d, "func", None), "id", None)) == "tool"
                for d in node.decorator_list
            )
            if not decorated:
                continue
            body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            bodies.setdefault(node.name, []).append((path.parent.name, body))
    return bodies


def _registered_tools() -> dict[str, set[str]]:
    """Map agent directory -> tool names passed to ``Agent(tools=[...])``."""
    registered: dict[str, set[str]] = {}
    for path in AGENT_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Agent":
                for kw in node.keywords:
                    if kw.arg == "tools" and isinstance(kw.value, ast.List):
                        names |= {e.id for e in kw.value.elts if isinstance(e, ast.Name)}
        registered[path.parent.name] = names
    return registered


def test_agent_sources_are_discoverable():
    assert len(AGENT_FILES) == 6, [p.parent.name for p in AGENT_FILES]


def test_no_allowlisted_tool_performs_a_mutating_operation():
    """The critical invariant: nothing gated-as-read-only may actually mutate."""
    offenders: list[str] = []
    for name, occurrences in _tool_bodies().items():
        if name not in READ_ONLY_TOOLS:
            continue
        if name in _VERIFIED_READ_ONLY_DESPITE_KEYWORD:
            continue
        for agent, body in occurrences:
            sql_hit = _MUTATING_SQL.search(body)
            api_hit = _MUTATING_API.search(body)
            if sql_hit or api_hit:
                offenders.append(
                    f"{agent}:{name} -> "
                    f"sql={sql_hit.group(0) if sql_hit else None} "
                    f"api={api_hit.group(1) if api_hit else None}"
                )
    assert not offenders, (
        "Tools on the read-only allowlist appear to mutate state. Either remove "
        "them from READ_ONLY_TOOLS in src/hooks/tier3_gate.py, or (if the match "
        "is inside a read-only query) document them in "
        "_VERIFIED_READ_ONLY_DESPITE_KEYWORD after reading the code:\n  " + "\n  ".join(offenders)
    )


def test_allowlist_has_no_stale_entries():
    """Every allowlisted name must correspond to a real tool."""
    known = set(_tool_bodies())
    stale = sorted(READ_ONLY_TOOLS - known)
    assert not stale, f"READ_ONLY_TOOLS lists tools that no longer exist: {stale}"


@pytest.mark.parametrize(
    "tool",
    [
        "execute_sql",
        "execute_sql_on_dev",
        "drop_db_user",
        "create_db_user",
        "kill_session",
        "kill_connection",
        "create_index",
        "execute_vacuum",
        "reindex_concurrently",
        "trigger_backup",
        "put_item",
        "batch_write_items",
        "load_data_from_s3",
        "load_data_from_csv",
        "load_items_from_s3",
        "export_table_to_s3",
        "share_data_snapshot",
        "clone_to_lower_env",
        "setup_data_masking",
        "replicate_table_with_masking",
        "modify_instance_class",
        "modify_capacity",
        "modify_parameter",
        "switch_billing_mode",
        "gather_table_stats",
        "add_gsi",
        "clone_table_structure",
        "create_backup",
        "create_read_replica",
        "configure_aurora_autoscaling",
    ],
)
def test_destructive_tools_require_approval(tool):
    assert requires_approval(tool) is True


def test_every_registered_tool_is_classified_consistently():
    """No registered tool may be both absent from the allowlist and ungated.

    Classification is total by construction (anything unknown is gated), so this
    asserts the complementary property: the allowlist and the gate agree.
    """
    for agent, tools in _registered_tools().items():
        assert tools, f"{agent} registers no tools"
        for tool in tools:
            gated = requires_approval(tool)
            assert gated == (tool not in READ_ONLY_TOOLS), f"{agent}:{tool}"


def test_all_agents_wire_the_tier3_hook():
    for path in AGENT_FILES:
        source = path.read_text(encoding="utf-8")
        assert "Tier3ApprovalHook(" in source, f"{path.parent.name} does not build the hook"
        assert "hooks=[tier3]" in source, f"{path.parent.name} does not pass hooks= to Agent()"


def test_no_agent_sets_bypass_tool_consent():
    """``BYPASS_TOOL_CONSENT`` must never be re-introduced."""
    for path in AGENT_FILES:
        source = path.read_text(encoding="utf-8")
        assert 'os.environ["BYPASS_TOOL_CONSENT"]' not in source, path.parent.name
        assert "BYPASS_TOOL_CONSENT'] =" not in source, path.parent.name


def test_all_agents_return_pending_approvals_on_interrupt():
    for path in AGENT_FILES:
        source = path.read_text(encoding="utf-8")
        assert "awaiting_approval" in source, f"{path.parent.name} drops interrupt state"
        assert "pending_approvals(result)" in source, path.parent.name
