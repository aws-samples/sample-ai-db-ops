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

"""Tests for the git ingester path classification + event shaping (R4.3)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.admin_ops.changefeed.ingest import git as gi


def test_classify_agent_code_medium():
    matches = dict((p, (c, s, e)) for p, c, s, e in gi.iter_matching_paths(
        ["deploy/postgresql_agent/agent.py"]
    ))
    cat, sev, eng = matches["deploy/postgresql_agent/agent.py"]
    assert cat == "agent_code"
    assert sev == "medium"
    assert eng == "postgresql"


def test_classify_iam_policy_high():
    out = gi.iter_matching_paths(["infra/agent-permissions-policy.json"])
    assert out == [("infra/agent-permissions-policy.json", "iam_policy", "high", None)]


def test_classify_infra_yaml_high():
    out = gi.iter_matching_paths(["infra/cloudformation-account-specific.yaml"])
    assert out[0][1] == "db_infra"
    assert out[0][2] == "high"


def test_classify_config_yaml_high():
    out = gi.iter_matching_paths(["config.yaml"])
    assert out == [("config.yaml", "fleet_config", "high", None)]


def test_classify_sql_template_medium_with_engine():
    out = gi.iter_matching_paths(
        ["src/admin_ops/registry/templates/oracle/get_slow_queries.yaml"]
    )
    assert out[0][1] == "sql_template"
    assert out[0][2] == "medium"
    assert out[0][3] == "oracle"


def test_unrelated_paths_are_ignored():
    out = gi.iter_matching_paths(
        ["README.md", "ui/src/app/page.tsx", "tests/admin_ops/__init__.py"]
    )
    assert out == []


def test_commit_url_derivation_has_no_account_ids():
    # The derived URL must never embed account/resource ids -- only the
    # remote path. We can't assert the exact remote here, but we can assert
    # the function returns a string and doesn't crash.
    url = gi._commit_url("abc123")
    assert isinstance(url, str)
    # 12-digit run would be an account id; ensure none leaked.
    import re

    assert not re.search(r"(?<!\d)\d{12}(?!\d)", url)


# ── Revision names reaching the git argv are validated ────────────────────────


def test_validate_revision_accepts_ordinary_revision_names():
    for revision in (
        "HEAD",
        "main",
        "origin/main",
        "v1.2.3",
        "release/2026-01",
        "abc123def456",
        "v1.0~3",
        "v1.0^2",
    ):
        assert gi._validate_revision(revision) == revision


def test_validate_revision_refuses_option_shaped_values():
    """A leading dash would be read by git as an option, not a revision.

    No shell is involved, so this is argument injection rather than command
    injection: the concern is turning a history walk into a differently-behaving
    git invocation.
    """
    import pytest

    for revision in ("--output=/tmp/x", "-n999", "--upload-pack=sh", "--help"):
        with pytest.raises(ValueError, match="Invalid git revision"):
            gi._validate_revision(revision)


def test_validate_revision_refuses_shell_and_whitespace_shapes():
    import pytest

    for revision in ("; rm -rf /", "$(id)", "`id`", "a b", "", "a\nb", "a|b"):
        with pytest.raises(ValueError, match="Invalid git revision"):
            gi._validate_revision(revision)


def test_ingest_history_validates_since_before_building_argv(monkeypatch):
    """The guard must sit in front of the argv, not merely exist.

    Asserts _git is never reached for a rejected revision, so the validation
    cannot be bypassed by a future reordering of ingest_history.
    """
    import pytest

    calls = []
    monkeypatch.setattr(gi, "_git", lambda args: calls.append(args) or "")

    with pytest.raises(ValueError, match="Invalid git revision"):
        gi.ingest_history(since="--output=/tmp/pwned")

    assert calls == [], f"_git was reached with a rejected revision: {calls}"
