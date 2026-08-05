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

"""Tier-aware runner contract tests."""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from src.admin_ops.admin.sql import runner as runner_mod
from src.admin_ops.admin.sql.runner import (
    AgentInvocationFailed,
    TierThreeRequiresApply,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    audit_log: list[dict[str, Any]] = []
    runner_mod.set_audit_emitter_for_testing(lambda e: audit_log.append(dict(e)))

    def _stub_direct(engine: str, sql: str, params: Mapping[str, Any] | None):
        return [{"col": 1}]

    def _stub_agent(engine: str, body: str, user_id: str):
        return {"agent_responded": True, "engine": engine}

    runner_mod.set_direct_exec_for_testing(_stub_direct)
    runner_mod.set_agent_invoker_for_testing(_stub_agent)

    yield audit_log

    runner_mod.set_direct_exec_for_testing(None)
    runner_mod.set_agent_invoker_for_testing(None)
    runner_mod.set_audit_emitter_for_testing(None)


def test_tier_1_executes_directly(_isolate):
    result = runner_mod.run(
        engine="postgresql", body="SELECT 1", user_id="alice"
    )
    assert result.classification.tier == "tier_1_read"
    assert result.rows == [{"col": 1}]
    assert result.forwarded_to_agent is False
    assert _isolate[-1]["outcome"] == "ok"


def test_tier_3_without_token_raises(_isolate):
    with pytest.raises(TierThreeRequiresApply):
        runner_mod.run(
            engine="mysql",
            body="DROP TABLE users",
            user_id="alice",
        )
    assert _isolate[-1]["outcome"] == "apply_token_missing"


def test_tier_3_with_correct_token_forwards(_isolate):
    result = runner_mod.run(
        engine="mysql",
        body="DROP TABLE users",
        user_id="alice",
        apply_token="APPLY",  # nosec B106  # confirmation token, not a password
    )
    assert result.forwarded_to_agent is True
    assert _isolate[-1]["outcome"] == "agent_ok"


def test_tier_3_lowercase_token_rejected(_isolate):
    with pytest.raises(TierThreeRequiresApply):
        runner_mod.run(
            engine="mysql",
            body="DELETE FROM x",
            user_id="alice",
            apply_token="apply",  # nosec B106  # confirmation token, not a password
        )


def test_agent_failure_propagates(_isolate):
    """A failed invocation is recorded, but without the exception message.

    Driver and agent errors can echo the submitted statement, so the audit
    record carries the exception *type* only. The full detail goes to the
    operator log via ``logging.exception``.
    """
    # Bandit's B105 reads any string assigned to a name it considers
    # credential-shaped as a hardcoded password. This is the opposite: it is
    # the sensitive text this test asserts must NOT reach the caller.
    secret_bearing_message = "agent down while running DROP TABLE x for alice"  # nosec B105

    def boom(engine, body, user_id):
        raise RuntimeError(secret_bearing_message)

    runner_mod.set_agent_invoker_for_testing(boom)
    with pytest.raises(AgentInvocationFailed) as raised:
        runner_mod.run(
            engine="postgresql",
            body="DROP TABLE x",
            user_id="alice",
            apply_token="APPLY",  # nosec B106  # confirmation token, not a password
        )
    assert _isolate[-1]["outcome"] == "agent_failed"
    assert _isolate[-1]["error"] == "RuntimeError"
    # The statement must not survive into the audit record or the raised error.
    assert secret_bearing_message not in _isolate[-1]["error"]
    assert secret_bearing_message not in str(raised.value)


def test_unrecognised_keyword_treated_as_tier_3(_isolate):
    with pytest.raises(TierThreeRequiresApply):
        runner_mod.run(
            engine="mysql", body="SUMMON elder_god;", user_id="alice"
        )


# ── The tier_2 failure path must redact exactly like tier_3 ───────────────────


def test_tier_2_agent_failure_does_not_leak_exception_text(_isolate):
    """The tier_2_advise path must not echo the agent failure message.

    This path calls the same ``_agent_invoke`` as tier_3, so its failure payload
    can quote the submitted statement in the same way. It previously used
    ``str(exc)`` for both the audit record and the raised error while tier_3 used
    ``safe_error(exc)`` — the leak survived because the existing failure test
    passes ``apply_token="APPLY"`` and so only ever exercised tier_3.
    """
    sensitive = "agent down while advising on customers.ssn for alice"  # nosec B105

    def boom(engine, body, user_id):
        raise RuntimeError(sensitive)

    runner_mod.set_agent_invoker_for_testing(boom)

    with pytest.raises(runner_mod.AgentInvocationFailed) as excinfo:
        runner_mod.run(
            engine="postgresql", body="RECOMMEND indexes for customers", user_id="alice"
        )

    # Confirm the path under test really was tier_2, not tier_3.
    assert _isolate[-1]["tier"] == "tier_2_advise"
    assert _isolate[-1]["outcome"] == "agent_failed"

    assert sensitive not in str(excinfo.value)
    assert sensitive not in str(_isolate[-1]["error"])
    # The exception type is still available for diagnosis.
    assert "RuntimeError" in str(_isolate[-1]["error"])


def test_runner_never_uses_raw_str_exc():
    """Drift guard: every caught exception in the runner goes through safe_error.

    ``str(exc)`` in this module puts the driver or agent message into an audit
    record or a raised error, both of which reach the caller.
    """
    import pathlib

    source = pathlib.Path(runner_mod.__file__).read_text(encoding="utf-8")
    offenders = [
        f"line {i}: {line.strip()}"
        for i, line in enumerate(source.splitlines(), 1)
        if "str(exc" in line and "safe_error" not in line
    ]
    assert not offenders, (
        "Use safe_error(exc) so the caller receives the exception type only:\n  "
        + "\n  ".join(offenders)
    )
