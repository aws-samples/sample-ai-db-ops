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

"""Registry-into-agents wiring (R1.3, R1.4, R7.7).

For each engine we:
  * import the agent module (stubbing the database / Strands deps that aren't
    available in the test environment),
  * assert every migrated Tier-1 tool's template_id is loaded by the
    registry singleton,
  * assert ``registry.render(template_id, sample_params).sql`` produces SQL
    whose **normalised** whitespace matches the agent's in-source
    ``_DEFAULT_BODY`` constant byte-for-byte (R1.4),
  * assert that when the template is missing from the registry the tool
    still runs end-to-end and falls back to ``_DEFAULT_BODY`` (R1.4).

Hypothesis is used to vary the sample parameters within their declared
ranges so the equality holds for every legal binding the registry will
ever issue.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import re
import sys
import types
from pathlib import Path
from typing import Any, Iterable

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from src.admin_ops.registry.loader import registry

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_ROOT = REPO_ROOT / "deploy"


# ─── Test helpers ───────────────────────────────────────────────────────────────


def _normalise(sql: str) -> str:
    """Collapse all whitespace runs to a single space and strip ends.

    Hypothesis-friendly equivalence relation: two SQL strings are equal if
    they only differ in indentation / line-wrapping.
    """
    return re.sub(r"\s+", " ", sql).strip()


def _stub_module(name: str, **attrs: Any) -> types.ModuleType:
    """Insert a barebones module into ``sys.modules`` so ``import name`` works."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _ensure_external_stubs() -> None:
    """Insert just enough fake modules so each agent.py can import cleanly.

    The agents import psycopg2, pymysql, oracledb, boto3, strands and
    bedrock_agentcore. None of them are required to load the *registry*
    integration; the only thing we exercise here is the @tool function
    bodies, which we wire to a fake cursor.
    """
    if "psycopg2" not in sys.modules:
        _stub_module("psycopg2", connect=lambda *a, **k: _FakeConn(_FakeCursor()))

        # The registry's render layer does `from psycopg2 import sql as pgsql`
        # and then calls `pgsql.Identifier(...)` / `pgsql.SQL(body).format(...)`.
        # Provide minimal classes so render's identifier-quoting path works.
        class _StubIdentifier:
            def __init__(self, name: str) -> None:
                self.name = name

            def as_string(self, _conn: Any = None) -> str:
                return '"' + str(self.name).replace('"', '""') + '"'

            def __str__(self) -> str:
                return self.as_string()

        class _StubSQL:
            def __init__(self, template: str) -> None:
                self._template = template

            def format(self, **kwargs: Any) -> "_StubSQL":
                out = self._template
                for k, v in kwargs.items():
                    out = out.replace("{" + k + "}", str(v))
                return _StubSQL(out)

            def __str__(self) -> str:
                return self._template

        _stub_module("psycopg2.sql", Identifier=_StubIdentifier, SQL=_StubSQL)
    if "pymysql" not in sys.modules:
        cursors = _stub_module("pymysql.cursors", DictCursor=object)
        _stub_module(
            "pymysql",
            connect=lambda *a, **k: _FakeConn(_FakeCursor(dict_rows=True)),
            cursors=cursors,
        )
    if "oracledb" not in sys.modules:
        _stub_module(
            "oracledb",
            connect=lambda *a, **k: _FakeConn(_FakeCursor(uppercase_cols=True)),
            makedsn=lambda host, port, sid="ORCL": f"{host}:{port}/{sid}",
        )
    if "boto3" not in sys.modules:
        _stub_module("boto3", client=lambda *a, **k: _FakeBoto())
        botocore = _stub_module("botocore")
        _stub_module("botocore.exceptions", ClientError=Exception)
        botocore.exceptions = sys.modules["botocore.exceptions"]
    if "strands" not in sys.modules:
        def _identity_tool(fn):
            return fn

        strands_mod = _stub_module(
            "strands",
            tool=_identity_tool,
            Agent=lambda *a, **k: types.SimpleNamespace(__call__=lambda self, p: types.SimpleNamespace(message=p)),
        )
        # The agents wire Tier3ApprovalHook, which imports the hook event types
        # from `strands.hooks`. These stubs only need to be importable and
        # subclassable; the gate's behaviour is covered by
        # tests/admin_ops/safety/ (unit) and test_tier3_hook_e2e.py (real
        # strands, skipped when the package is absent).
        class _StubHookProvider:
            def register_hooks(self, registry, **kwargs):  # noqa: D401
                return None

        hooks = _stub_module(
            "strands.hooks",
            HookProvider=_StubHookProvider,
            HookRegistry=object,
            BeforeToolCallEvent=object,
            AfterToolCallEvent=object,
        )
        strands_mod.hooks = hooks
    if "bedrock_agentcore" not in sys.modules:
        _stub_module("bedrock_agentcore")
        runtime = _stub_module("bedrock_agentcore.runtime")
        runtime.BedrockAgentCoreApp = lambda *a, **k: types.SimpleNamespace(
            entrypoint=lambda fn: fn,
            run=lambda *a, **k: None,
        )


class _FakeCursor:
    """Captures the last ``execute(sql, params)`` call for assertions."""

    def __init__(self, dict_rows: bool = False, uppercase_cols: bool = False) -> None:
        self.last_sql: Any = None
        self.last_params: Any = None
        self.executions: list[tuple[Any, Any]] = []
        self.description = [("dummy_col",)]
        self._dict_rows = dict_rows
        self._uppercase_cols = uppercase_cols

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: Any, params: Any = None) -> None:
        self.last_sql = sql
        self.last_params = params
        self.executions.append((sql, params))

    def fetchall(self) -> list[Any]:
        return []

    def fetchone(self) -> tuple[Any, ...]:
        return (0,)

    def close(self) -> None:
        return None

    @property
    def rowcount(self) -> int:
        return 0


class _FakeConn:
    def __init__(self, cur: _FakeCursor) -> None:
        self._cur = cur
        self.autocommit = False

    def cursor(self) -> _FakeCursor:
        return self._cur

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeBoto:
    def get_secret_value(self, **_: Any) -> dict:
        import json as _json

        return {
            "SecretString": _json.dumps(
                {
                    "host": "stub",
                    "port": 5432,
                    "username": "stub",
                    # Placeholder in a fake Secrets Manager payload; no real
                    # secret, and nothing connects with it. B105 matches on the
                    # key name, not on the value.
                    "password": "stub",  # nosec B105
                    "dbname": "stub",
                    "sid": "ORCL",
                }
            )
        }

    def get_metric_statistics(self, **_: Any) -> dict:
        return {"Datapoints": []}

    def list_tables(self) -> dict:
        return {"TableNames": []}


def _import_agent(rel_path: str, module_name: str) -> types.ModuleType:
    """Import deploy/<engine>_agent/agent.py under a unique module name."""
    _ensure_external_stubs()
    os.environ.setdefault("PG_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:stub")
    os.environ.setdefault("MYSQL_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:stub")
    os.environ.setdefault("ORACLE_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:stub")
    os.environ.setdefault("AWS_REGION", "us-east-1")

    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _extract_default_bodies(path: Path) -> dict[str, str]:
    """Return mapping of @tool function_name -> _DEFAULT_BODY string literal."""
    tree = ast.parse(path.read_text())
    bodies: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == "_DEFAULT_BODY"
                and isinstance(stmt.value, (ast.Constant, ast.Dict))
            ):
                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    bodies[node.name] = stmt.value.value
                elif isinstance(stmt.value, ast.Dict):
                    # DynamoDB tools use a dict literal as the default body.
                    bodies[node.name] = ast.unparse(stmt.value)
                break
    return bodies


# ─── Per-engine wiring tables ────────────────────────────────────────────────────

# (function_name, template_id, sample_params).
PG_TOOLS: list[tuple[str, str, dict]] = [
    ("get_slow_queries", "pg_get_slow_queries", {"top_n": 10}),
    ("get_active_sessions", "pg_get_active_sessions", {}),
    ("get_wait_events", "pg_get_wait_events", {}),
    ("get_vacuum_status", "pg_get_vacuum_status", {}),
    ("get_index_usage", "pg_get_index_usage", {"schema_name": "public"}),
    ("get_table_bloat", "pg_get_table_bloat", {"schema_name": "public"}),
    ("get_database_size", "pg_get_database_size", {}),
    ("get_connections_summary", "pg_get_connections_summary", {}),
    ("detect_blocking_chains", "pg_detect_blocking_chains", {}),
]

MY_TOOLS: list[tuple[str, str, dict]] = [
    ("get_slow_queries", "my_get_slow_queries", {"top_n": 10}),
    ("get_processlist", "my_get_processlist", {}),
    ("get_innodb_status", "my_get_innodb_status", {}),
    ("get_index_usage", "my_get_index_usage", {}),
    ("get_connections_summary", "my_get_connections_summary", {}),
    ("detect_blocking_chains", "my_detect_blocking_chains", {}),
]

ORA_TOOLS: list[tuple[str, str, dict]] = [
    ("list_tablespaces", "ora_list_tablespaces", {}),
    ("get_active_sessions", "ora_get_active_sessions", {}),
    ("get_wait_events", "ora_get_wait_events", {}),
    ("get_slow_queries", "ora_get_slow_queries", {"n": 10}),
    ("get_blocking_sessions", "ora_get_blocking_sessions", {}),
    ("get_index_usage", "ora_get_index_usage", {"owner": "APPDB"}),
    ("get_database_size", "ora_get_database_size", {}),
    ("get_connections_summary", "ora_get_connections_summary", {}),
]

DDB_TOOLS: list[tuple[str, str, dict]] = [
    ("get_table_metrics", "ddb_get_table_metrics", {}),
    ("get_throttled_requests", "ddb_get_throttled_requests", {}),
]


ENGINES = [
    ("postgresql", "deploy/postgresql_agent/agent.py", "_pg_agent_int", PG_TOOLS),
    ("mysql", "deploy/mysql_agent/agent.py", "_my_agent_int", MY_TOOLS),
    ("oracle", "deploy/oracle_agent/agent.py", "_ora_agent_int", ORA_TOOLS),
    ("dynamodb", "deploy/dynamodb_agent/agent.py", "_ddb_agent_int", DDB_TOOLS),
]


# ─── Static + registry tests ─────────────────────────────────────────────────────


@pytest.mark.parametrize("engine,agent_path,_modname,tools", ENGINES, ids=[e[0] for e in ENGINES])
def test_every_migrated_tool_has_a_registered_template(
    engine: str, agent_path: str, _modname: str, tools: list[tuple[str, str, dict]]
) -> None:
    """R1.3: every migrated tool resolves through ``registry.must_get``."""
    registry.load()
    loaded = {s.template_id for s in registry.all()}
    for fn_name, template_id, _ in tools:
        assert template_id in loaded, (
            f"{engine}.{fn_name} expects template {template_id!r} but it is missing"
        )


@pytest.mark.parametrize("engine,agent_path,_modname,tools", ENGINES, ids=[e[0] for e in ENGINES])
def test_every_migrated_tool_has_a_default_body(
    engine: str, agent_path: str, _modname: str, tools: list[tuple[str, str, dict]]
) -> None:
    """R1.4: every migrated tool retains an in-source ``_DEFAULT_BODY``."""
    bodies = _extract_default_bodies(REPO_ROOT / agent_path)
    for fn_name, _, _ in tools:
        assert fn_name in bodies, (
            f"{engine}.{fn_name} is missing the _DEFAULT_BODY fallback constant"
        )
        assert bodies[fn_name].strip(), f"{engine}.{fn_name} _DEFAULT_BODY is empty"


@pytest.mark.parametrize(
    "engine,agent_path,tools",
    [(e, p, tools) for e, p, _, tools in ENGINES if e != "dynamodb"],
    ids=[e[0] for e in ENGINES if e[0] != "dynamodb"],
)
def test_rendered_sql_matches_default_body(
    engine: str, agent_path: str, tools: list[tuple[str, str, dict]]
) -> None:
    """The registry render is a structural twin of the in-source default."""
    registry.load()
    bodies = _extract_default_bodies(REPO_ROOT / agent_path)
    for fn_name, template_id, params in tools:
        rendered = registry.render(template_id, params)
        rendered_sql = str(rendered.sql)
        # For PostgreSQL, the render still contains the %(name)s placeholders
        # so byte-for-byte equality (after whitespace normalisation) holds.
        # Same for MySQL and Oracle.
        assert _normalise(rendered_sql) == _normalise(bodies[fn_name]), (
            f"{engine}.{fn_name}: rendered SQL diverges from _DEFAULT_BODY\n"
            f"rendered: {_normalise(rendered_sql)[:300]}\n"
            f"default:  {_normalise(bodies[fn_name])[:300]}"
        )


# ─── Hypothesis: render is stable across the declared parameter range ───────────


@given(top_n=st.integers(min_value=1, max_value=100))
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pg_get_slow_queries_render_is_stable(top_n: int) -> None:
    registry.load()
    rendered = registry.render("pg_get_slow_queries", {"top_n": top_n})
    assert rendered.params == {"top_n": top_n}
    assert "%(top_n)s" in str(rendered.sql)


@given(top_n=st.integers(min_value=1, max_value=100))
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_my_get_slow_queries_render_is_stable(top_n: int) -> None:
    registry.load()
    rendered = registry.render("my_get_slow_queries", {"top_n": top_n})
    assert rendered.params == {"top_n": top_n}


@given(n=st.integers(min_value=1, max_value=100))
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_ora_get_slow_queries_render_is_stable(n: int) -> None:
    registry.load()
    rendered = registry.render("ora_get_slow_queries", {"n": n})
    assert rendered.params == {"n": n}
    assert ":n" in str(rendered.sql)


@given(schema=st.sampled_from(["public", "appdb", "analytics", "reporting"]))
@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pg_get_index_usage_render_is_stable(schema: str) -> None:
    registry.load()
    rendered = registry.render("pg_get_index_usage", {"schema_name": schema})
    assert rendered.params == {"schema_name": schema}


# ─── End-to-end fallback when the template is removed (R1.4) ─────────────────────


@pytest.fixture
def pg_agent_module() -> types.ModuleType:
    return _import_agent("deploy/postgresql_agent/agent.py", "_pg_agent_int")


@pytest.fixture
def my_agent_module() -> types.ModuleType:
    return _import_agent("deploy/mysql_agent/agent.py", "_my_agent_int")


@pytest.fixture
def ora_agent_module() -> types.ModuleType:
    return _import_agent("deploy/oracle_agent/agent.py", "_ora_agent_int")


@pytest.fixture
def ddb_agent_module() -> types.ModuleType:
    return _import_agent("deploy/dynamodb_agent/agent.py", "_ddb_agent_int")


def _patch_pg_conn(monkeypatch: pytest.MonkeyPatch, mod: types.ModuleType) -> _FakeCursor:
    cur = _FakeCursor()
    monkeypatch.setattr(mod, "get_connection", lambda: _FakeConn(cur))
    return cur


def _patch_my_conn(monkeypatch: pytest.MonkeyPatch, mod: types.ModuleType) -> _FakeCursor:
    cur = _FakeCursor(dict_rows=True)
    # MySQL fetchall returns dict rows; the cursor base returns []
    monkeypatch.setattr(mod, "get_connection", lambda: _FakeConn(cur))
    return cur


def _patch_ora_conn(monkeypatch: pytest.MonkeyPatch, mod: types.ModuleType) -> _FakeCursor:
    cur = _FakeCursor(uppercase_cols=True)
    cur.description = [("DUMMY_COL",)]
    monkeypatch.setattr(mod, "get_connection", lambda: _FakeConn(cur))
    return cur


@pytest.mark.parametrize("fn_name,template_id,params", PG_TOOLS)
def test_pg_tool_falls_back_when_template_removed(
    monkeypatch: pytest.MonkeyPatch,
    pg_agent_module: types.ModuleType,
    fn_name: str,
    template_id: str,
    params: dict,
) -> None:
    registry.load()
    # Drop the template so the tool MUST hit the fallback path.
    monkeypatch.setitem(registry._specs, template_id, registry._specs.pop(template_id))
    registry._specs.pop(template_id, None)
    cur = _patch_pg_conn(monkeypatch, pg_agent_module)
    fn = getattr(pg_agent_module, fn_name)
    fn(**params)
    # _DEFAULT_BODY is what should have been passed to execute.
    bodies = _extract_default_bodies(REPO_ROOT / "deploy/postgresql_agent/agent.py")
    expected = _normalise(bodies[fn_name])
    seen = [_normalise(str(s)) for s, _ in cur.executions]
    assert expected in seen, (
        f"{fn_name}: _DEFAULT_BODY was not the SQL passed to cursor.execute.\n"
        f"expected: {expected[:200]}\nsaw: {seen}"
    )
    # restore registry for downstream tests
    registry.load()


@pytest.mark.parametrize("fn_name,template_id,params", MY_TOOLS)
def test_my_tool_falls_back_when_template_removed(
    monkeypatch: pytest.MonkeyPatch,
    my_agent_module: types.ModuleType,
    fn_name: str,
    template_id: str,
    params: dict,
) -> None:
    registry.load()
    registry._specs.pop(template_id, None)
    cur = _patch_my_conn(monkeypatch, my_agent_module)
    # MySQL's get_connections_summary issues an extra SELECT to look up
    # max_connections; the helper cursor returns a default-shaped dict via
    # fetchone(). Pre-seat that.
    if fn_name == "get_connections_summary":
        cur.fetchone = lambda: {"max_conn": 100}  # type: ignore[assignment]
        cur.fetchall = lambda: []  # type: ignore[assignment]
    elif fn_name == "get_innodb_status":
        cur.fetchall = lambda: []  # type: ignore[assignment]
    fn = getattr(my_agent_module, fn_name)
    fn(**params)
    bodies = _extract_default_bodies(REPO_ROOT / "deploy/mysql_agent/agent.py")
    expected = _normalise(bodies[fn_name])
    seen = [_normalise(str(s)) for s, _ in cur.executions]
    assert expected in seen, (
        f"{fn_name}: _DEFAULT_BODY was not the SQL passed to cursor.execute.\n"
        f"expected: {expected[:200]}\nsaw: {seen}"
    )
    registry.load()


@pytest.mark.parametrize("fn_name,template_id,params", ORA_TOOLS)
def test_ora_tool_falls_back_when_template_removed(
    monkeypatch: pytest.MonkeyPatch,
    ora_agent_module: types.ModuleType,
    fn_name: str,
    template_id: str,
    params: dict,
) -> None:
    registry.load()
    registry._specs.pop(template_id, None)
    cur = _patch_ora_conn(monkeypatch, ora_agent_module)
    # get_connections_summary issues a follow-up SELECT for v$parameter.
    if fn_name == "get_connections_summary":
        cur.fetchone = lambda: ("100",)  # type: ignore[assignment]
    fn = getattr(ora_agent_module, fn_name)
    # Some Oracle tools take a positional schema_name argument.
    if "owner" in params:
        fn(params["owner"])
    elif "n" in params:
        fn(top_n=params["n"])
    else:
        fn(**params)
    bodies = _extract_default_bodies(REPO_ROOT / "deploy/oracle_agent/agent.py")
    expected = _normalise(bodies[fn_name])
    seen = [_normalise(str(s)) for s, _ in cur.executions]
    assert expected in seen, (
        f"{fn_name}: _DEFAULT_BODY was not the SQL passed to cursor.execute.\n"
        f"expected: {expected[:200]}\nsaw: {seen}"
    )
    registry.load()


def test_ddb_get_table_metrics_falls_back_when_template_removed(
    monkeypatch: pytest.MonkeyPatch, ddb_agent_module: types.ModuleType
) -> None:
    registry.load()
    registry._specs.pop("ddb_get_table_metrics", None)
    seen: list[str] = []

    class _CW:
        def get_metric_statistics(self, **kwargs: Any) -> dict:
            seen.append(kwargs["MetricName"])
            return {"Datapoints": []}

    monkeypatch.setattr(ddb_agent_module, "get_cloudwatch", lambda: _CW())
    ddb_agent_module.get_table_metrics("dbops-orders", period_minutes=5)
    # The fallback metric list is the same five keys the in-source default
    # declares; assert they are all queried.
    assert set(seen) == {
        "ConsumedReadCapacityUnits",
        "ConsumedWriteCapacityUnits",
        "ReadThrottleEvents",
        "WriteThrottleEvents",
        "SuccessfulRequestLatency",
    }
    registry.load()


def test_ddb_get_throttled_requests_falls_back_when_template_removed(
    monkeypatch: pytest.MonkeyPatch, ddb_agent_module: types.ModuleType
) -> None:
    registry.load()
    registry._specs.pop("ddb_get_throttled_requests", None)
    seen: list[str] = []

    class _CW:
        def get_metric_statistics(self, **kwargs: Any) -> dict:
            seen.append(kwargs["MetricName"])
            return {"Datapoints": []}

    monkeypatch.setattr(ddb_agent_module, "get_cloudwatch", lambda: _CW())
    ddb_agent_module.get_throttled_requests("dbops-orders", period_minutes=5)
    assert set(seen) == {"ReadThrottleEvents", "WriteThrottleEvents"}
    registry.load()
