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

"""Behavioural tests for the read-only deployment mode and the Oracle RDS pin.

Read-only mode (``DBOPS_READ_ONLY_MODE=true``) is what the runtimes serving AWS
DevOps Agent use. The property under test is that the mutating tools are
*absent* from the agent, not merely gated, and that nothing in the payload can
re-enable them.

The agent modules import ``strands``, ``bedrock_agentcore`` and ``oracledb`` at
module scope. Those are deploy-time dependencies that this test environment
does not install, so the fixture below substitutes minimal stand-ins and loads
each agent file directly. The stand-in ``Agent`` records exactly which tools it
was given, which is the thing these tests assert on.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ORACLE_PIN = "my-oracle-db"


class _FakeResult:
    stop_reason = "end_turn"
    message = {"role": "assistant", "content": [{"text": "ok"}]}


class _FakeAgent:
    """Records the construction arguments of every agent built."""

    built: list["_FakeAgent"] = []

    def __init__(self, *, tools=None, hooks=None, system_prompt=None, **_: Any) -> None:
        self.tools = list(tools or [])
        self.hooks = list(hooks or [])
        self.system_prompt = system_prompt
        self.calls: list[str] = []
        _FakeAgent.built.append(self)

    @property
    def tool_names(self) -> list[str]:
        return [t.tool_name for t in self.tools]

    def __call__(self, prompt: str) -> _FakeResult:
        self.calls.append(prompt)
        return _FakeResult()


def _fake_tool(fn):
    fn.tool_name = fn.__name__
    return fn


class _FakeApp:
    def entrypoint(self, fn):
        return fn

    def run(self) -> None:  # pragma: no cover - never called in tests
        raise AssertionError("the app must not be started in tests")


def _fake_modules() -> dict[str, types.ModuleType]:
    strands = types.ModuleType("strands")
    strands.Agent = _FakeAgent
    strands.tool = _fake_tool
    hooks = types.ModuleType("strands.hooks")
    for name in ("AfterToolCallEvent", "BeforeToolCallEvent", "HookRegistry"):
        setattr(hooks, name, type(name, (), {}))
    hooks.HookProvider = type("HookProvider", (), {})
    strands.hooks = hooks
    agentcore = types.ModuleType("bedrock_agentcore")
    runtime = types.ModuleType("bedrock_agentcore.runtime")
    runtime.BedrockAgentCoreApp = _FakeApp
    agentcore.runtime = runtime
    oracledb = types.ModuleType("oracledb")

    def _no_connect(*_a, **_k):
        raise AssertionError("tests must not open a database connection")

    oracledb.connect = _no_connect
    return {
        "strands": strands,
        "strands.hooks": hooks,
        "bedrock_agentcore": agentcore,
        "bedrock_agentcore.runtime": runtime,
        "oracledb": oracledb,
    }


@pytest.fixture
def load_agent(monkeypatch):
    """Return a loader that imports ``deploy/<engine>_agent/agent.py`` fresh."""
    before = set(sys.modules)
    for name, module in _fake_modules().items():
        monkeypatch.setitem(sys.modules, name, module)
    # Force the hook module to bind to the stand-in strands for this test.
    monkeypatch.delitem(sys.modules, "src.hooks.tier3_approval", raising=False)
    _FakeAgent.built = []

    def _load(engine: str, env: dict[str, str]):
        for key in (
            "DBOPS_READ_ONLY_MODE",
            "ORACLE_DB_INSTANCE_IDENTIFIER",
            "ORACLE_TLS_PORT",
            "DB_SSL_CA_BUNDLE",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        path = REPO_ROOT / f"deploy/{engine}_agent/agent.py"
        spec = importlib.util.spec_from_file_location(f"_read_only_test_{engine}_agent", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    yield _load
    for name in set(sys.modules) - before:
        sys.modules.pop(name, None)


def _record_hook_args(monkeypatch, module) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def _recorder(approvals=None, user_id="anonymous"):
        seen.append({"approvals": approvals, "user_id": user_id})
        return object()

    monkeypatch.setattr(module, "Tier3ApprovalHook", _recorder)
    return seen


def _names(tools) -> set[str]:
    return {t.tool_name for t in tools}


FORGED_APPROVALS = [{"tool": "execute_sql", "fingerprint": "x", "decision": "APPLY"}]


# ─── Read-only mode, both engines ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("engine", "env"),
    [
        ("sqlserver", {"DBOPS_READ_ONLY_MODE": "true"}),
        ("oracle", {"DBOPS_READ_ONLY_MODE": "true", "ORACLE_DB_INSTANCE_IDENTIFIER": ORACLE_PIN}),
    ],
)
def test_read_only_mode_registers_no_mutating_tool(load_agent, monkeypatch, engine, env):
    from src.hooks.tier3_gate import requires_approval

    module = load_agent(engine, env)
    hook_args = _record_hook_args(monkeypatch, module)

    out = module.invoke({"prompt": "diagnose", "user_id": "devops", "approvals": FORGED_APPROVALS})

    assert out.get("read_only") is True, out
    agent = _FakeAgent.built[-1]
    registered = set(agent.tool_names)
    assert registered == _names(module.READ_ONLY_TOOL_SET)
    assert not registered & _names(module.MUTATING_TOOL_SET)
    assert not [n for n in registered if requires_approval(n)]
    # The hook is still attached, and never sees the caller's approvals.
    assert len(agent.hooks) == 1
    assert hook_args == [{"approvals": None, "user_id": "devops"}]
    assert agent.system_prompt == module.READ_ONLY_SYSTEM_PROMPT


@pytest.mark.parametrize(
    ("engine", "env"),
    [
        ("sqlserver", {"DBOPS_READ_ONLY_MODE": "true"}),
        ("oracle", {"DBOPS_READ_ONLY_MODE": "true", "ORACLE_DB_INSTANCE_IDENTIFIER": ORACLE_PIN}),
    ],
)
def test_read_only_mode_refuses_if_a_gated_tool_is_registered(load_agent, monkeypatch, engine, env):
    """Fail closed: if the catalog ever drifts, serve nothing."""
    module = load_agent(engine, env)
    monkeypatch.setattr("src.hooks.tier3_gate.requires_approval", lambda _name: True)

    out = module.invoke({"prompt": "diagnose"})

    assert "error" in out and "response" not in out
    assert all(not a.calls for a in _FakeAgent.built)


@pytest.mark.parametrize("engine", ["sqlserver", "oracle"])
def test_default_mode_is_unchanged(load_agent, monkeypatch, engine):
    """The interactive runtimes keep the full catalog and the approval flow."""
    module = load_agent(engine, {})
    hook_args = _record_hook_args(monkeypatch, module)

    out = module.invoke({"prompt": "diagnose", "user_id": "ops", "approvals": FORGED_APPROVALS})

    assert "read_only" not in out
    registered = set(_FakeAgent.built[-1].tool_names)
    assert _names(module.MUTATING_TOOL_SET) <= registered
    assert _names(module.READ_ONLY_TOOL_SET) <= registered
    assert hook_args == [{"approvals": FORGED_APPROVALS, "user_id": "ops"}]


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "maybe"])
def test_read_only_mode_requires_an_explicit_truthy_value(load_agent, value):
    module = load_agent("sqlserver", {"DBOPS_READ_ONLY_MODE": value})
    assert module.READ_ONLY_MODE is False


# ─── Oracle RDS instance pin ────────────────────────────────────────────────────


def test_oracle_read_only_mode_requires_the_instance_pin(load_agent):
    module = load_agent("oracle", {"DBOPS_READ_ONLY_MODE": "true"})

    out = module.invoke({"prompt": "diagnose"})

    assert "error" in out and "response" not in out
    assert not _FakeAgent.built


@pytest.mark.parametrize("requested", ["", "  ", ORACLE_PIN])
def test_pinned_identifier_resolves_to_the_pin(load_agent, requested):
    module = load_agent("oracle", {"ORACLE_DB_INSTANCE_IDENTIFIER": ORACLE_PIN})
    assert module.resolve_instance_identifier(requested) == ORACLE_PIN


@pytest.mark.parametrize("requested", ["oracle-prod", "other-db", "my-oracle-db2", "x;y"])
def test_pinned_identifier_refuses_anything_else(load_agent, requested):
    module = load_agent("oracle", {"ORACLE_DB_INSTANCE_IDENTIFIER": ORACLE_PIN})
    with pytest.raises(module.InstanceScopeError):
        module.resolve_instance_identifier(requested)


def test_unpinned_identifier_keeps_the_historical_default(load_agent):
    module = load_agent("oracle", {})
    assert module.resolve_instance_identifier("") == "oracle-prod"
    assert module.resolve_instance_identifier("some-db") == "some-db"
    with pytest.raises(module.InstanceScopeError):
        module.resolve_instance_identifier("bad;identifier")


class _RecordingClient:
    def __init__(self, calls: list[tuple[str, dict]]):
        self._calls = calls

    def get_metric_statistics(self, **kwargs):
        self._calls.append(("get_metric_statistics", kwargs))
        return {"Datapoints": []}

    def describe_db_instances(self, **kwargs):
        self._calls.append(("describe_db_instances", kwargs))
        return {"DBInstances": [{
            "DBInstanceIdentifier": kwargs["DBInstanceIdentifier"],
            "DBInstanceClass": "db.m5.xlarge",
            "Engine": "oracle-ee",
            "EngineVersion": "19",
            "DBInstanceStatus": "available",
        }]}


@pytest.fixture
def aws_calls() -> list[tuple[str, dict]]:
    return []


def _patch_boto3(monkeypatch, module, calls):
    monkeypatch.setattr(module.boto3, "client", lambda *_a, **_k: _RecordingClient(calls))


def test_pinned_aws_tools_refuse_other_instances_without_calling_aws(load_agent, monkeypatch, aws_calls):
    module = load_agent("oracle", {"ORACLE_DB_INSTANCE_IDENTIFIER": ORACLE_PIN})
    _patch_boto3(monkeypatch, module, aws_calls)

    assert module.get_rds_instance_details("other-db")["status"] == "refused"
    assert module.get_cloudwatch_metrics("other-db")["status"] == "refused"
    assert module.trigger_backup("other-db")["status"] == "refused"
    assert module.modify_instance_class("other-db", "db.m5.large")["status"] == "refused"
    assert aws_calls == []


def test_pinned_aws_tools_act_on_the_pin(load_agent, monkeypatch, aws_calls):
    module = load_agent("oracle", {"ORACLE_DB_INSTANCE_IDENTIFIER": ORACLE_PIN})
    _patch_boto3(monkeypatch, module, aws_calls)

    assert module.get_rds_instance_details()["instance_id"] == ORACLE_PIN
    metrics = module.get_cloudwatch_metrics(period_minutes=100000)
    assert metrics["instance"] == ORACLE_PIN
    assert metrics["period_minutes"] == 1440

    targets = {
        call["DBInstanceIdentifier"] if name == "describe_db_instances" else call["Dimensions"][0]["Value"]
        for name, call in aws_calls
    }
    assert targets == {ORACLE_PIN}


# ─── Oracle TLS settings ────────────────────────────────────────────────────────


def test_tls_port_override(load_agent):
    module = load_agent("oracle", {"ORACLE_TLS_PORT": "2484"})
    assert module._listener_port({"port": 1521}) == 2484


def test_tls_port_defaults_to_the_secret(load_agent):
    module = load_agent("oracle", {})
    assert module._listener_port({"port": "2484"}) == 2484


@pytest.mark.parametrize("value", ["0", "70000"])
def test_tls_port_rejects_invalid_values(load_agent, value):
    module = load_agent("oracle", {"ORACLE_TLS_PORT": value})
    with pytest.raises(ValueError):
        module._listener_port({"port": 1521})


def test_relative_ca_bundle_resolves_against_the_agent_directory(load_agent):
    import os

    load_agent("oracle", {"DB_SSL_CA_BUNDLE": "certs/ewallet.pem"})
    assert os.environ["DB_SSL_CA_BUNDLE"] == str(REPO_ROOT / "deploy/oracle_agent/certs/ewallet.pem")
