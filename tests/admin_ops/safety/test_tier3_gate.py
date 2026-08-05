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

"""Tier-3 approval gate decision logic.

These tests cover the properties the gate's security depends on: it fails
closed, an approval authorizes exactly one operation, and nothing an attacker
can put in the payload turns into an approval for a different operation.
"""

from src.hooks.tier3_gate import (
    APPLY,
    DENY,
    READ_ONLY_TOOLS,
    approval_request,
    find_decision,
    operation_fingerprint,
    parse_approvals,
    requires_approval,
)


# ── Classification is fail-closed ───────────────────────────────────────────


def test_known_read_only_tool_does_not_require_approval():
    assert requires_approval("get_slow_queries") is False
    assert requires_approval("list_tables") is False


def test_known_mutating_tool_requires_approval():
    for tool in ("execute_sql", "drop_db_user", "kill_session", "put_item"):
        assert requires_approval(tool) is True, tool


def test_unknown_tool_requires_approval():
    """A tool nobody classified must be gated, not silently allowed."""
    assert requires_approval("some_tool_added_next_quarter") is True


def test_blank_and_non_string_tool_names_require_approval():
    assert requires_approval("") is True
    assert requires_approval("   ") is True
    assert requires_approval(None) is True  # type: ignore[arg-type]
    assert requires_approval(42) is True  # type: ignore[arg-type]


def test_whitespace_padding_does_not_evade_classification():
    """Padding a read-only name must not change the verdict either way."""
    assert requires_approval("  get_slow_queries  ") is False
    assert requires_approval("  execute_sql  ") is True


# ── Fingerprints bind an approval to one operation ──────────────────────────


def test_fingerprint_is_stable_across_key_order():
    left = operation_fingerprint("create_index", {"table": "orders", "col": "id"})
    right = operation_fingerprint("create_index", {"col": "id", "table": "orders"})
    assert left == right


def test_fingerprint_changes_with_arguments():
    keep = operation_fingerprint("execute_sql", {"sql": "SELECT 1"})
    drop = operation_fingerprint("execute_sql", {"sql": "DROP TABLE customers"})
    assert keep != drop


def test_fingerprint_changes_with_tool_name():
    args = {"sql": "SELECT 1"}
    assert operation_fingerprint("execute_sql", args) != operation_fingerprint(
        "execute_sql_on_dev", args
    )


def test_fingerprint_handles_missing_and_nested_input():
    assert operation_fingerprint("trigger_backup", None)
    assert operation_fingerprint("load_data_from_s3", {"opts": {"b": [1, 2]}})


# ── Decision lookup ─────────────────────────────────────────────────────────


def _approval(tool, tool_input, decision=APPLY):
    return [
        {
            "tool": tool,
            "fingerprint": operation_fingerprint(tool, tool_input),
            "decision": decision,
        }
    ]


def test_no_approvals_yields_no_decision():
    assert find_decision(parse_approvals(None), "execute_sql", {"sql": "DROP TABLE t"}) is None
    assert find_decision(parse_approvals([]), "execute_sql", {"sql": "DROP TABLE t"}) is None


def test_matching_approval_is_found():
    args = {"sql": "DROP TABLE customers"}
    approvals = parse_approvals(_approval("execute_sql", args))
    assert find_decision(approvals, "execute_sql", args) == APPLY


def test_deny_decision_is_returned_verbatim():
    args = {"sql": "DROP TABLE customers"}
    approvals = parse_approvals(_approval("execute_sql", args, DENY))
    assert find_decision(approvals, "execute_sql", args) == DENY


def test_approval_for_different_arguments_does_not_match():
    """An APPLY for one statement cannot be replayed against another."""
    approvals = parse_approvals(_approval("execute_sql", {"sql": "SELECT 1"}))
    assert find_decision(approvals, "execute_sql", {"sql": "DROP TABLE customers"}) is None


def test_approval_for_different_tool_does_not_match():
    args = {"sql": "DROP TABLE customers"}
    approvals = parse_approvals(_approval("execute_sql_on_dev", args))
    assert find_decision(approvals, "execute_sql", args) is None


def test_forged_fingerprint_does_not_match():
    approvals = parse_approvals(
        [{"tool": "execute_sql", "fingerprint": "deadbeef", "decision": APPLY}]
    )
    assert find_decision(approvals, "execute_sql", {"sql": "DROP TABLE t"}) is None


def test_wildcard_style_fingerprint_does_not_match():
    for bogus in ("*", "", "0" * 64, "APPLY"):
        approvals = parse_approvals(
            [{"tool": "execute_sql", "fingerprint": bogus, "decision": APPLY}]
        )
        assert find_decision(approvals, "execute_sql", {"sql": "DROP TABLE t"}) is None, bogus


# ── Payload parsing is defensive ────────────────────────────────────────────


def test_malformed_approvals_are_dropped():
    assert parse_approvals("APPLY") == ()
    assert parse_approvals({"tool": "execute_sql"}) == ()
    assert parse_approvals([None, 3, "x"]) == ()
    assert parse_approvals([{"tool": "execute_sql"}]) == ()  # no fingerprint
    assert parse_approvals([{"fingerprint": "abc", "decision": APPLY}]) == ()  # no tool
    assert parse_approvals([{"tool": "t", "fingerprint": "f", "decision": ""}]) == ()


def test_valid_and_invalid_entries_can_coexist():
    args = {"sql": "DROP TABLE customers"}
    raw = [{"garbage": True}, *_approval("execute_sql", args)]
    approvals = parse_approvals(raw)
    assert len(approvals) == 1
    assert find_decision(approvals, "execute_sql", args) == APPLY


# ── Operator-facing request payload ─────────────────────────────────────────


def test_approval_request_describes_the_exact_operation():
    args = {"sql": "DROP TABLE customers"}
    request = approval_request("execute_sql", args)
    assert request["kind"] == "tier3_approval_required"
    assert request["tool"] == "execute_sql"
    assert request["input"] == args
    assert request["fingerprint"] == operation_fingerprint("execute_sql", args)
    assert request["apply_token"] == APPLY
    # The operator must be shown what will run, so the arguments are present.
    assert "DROP TABLE customers" in str(request["input"])


def test_read_only_allowlist_is_non_trivial():
    """Guard against the allowlist being emptied or replaced by a catch-all."""
    assert len(READ_ONLY_TOOLS) > 30
    assert "execute_sql" not in READ_ONLY_TOOLS
    assert "*" not in READ_ONLY_TOOLS
