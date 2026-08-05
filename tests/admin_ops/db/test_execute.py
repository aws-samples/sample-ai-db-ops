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

"""Unit tests for `src.admin_ops.db.execute.execute_with_params`."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.admin_ops.db.execute import UnsafeSqlError, execute_with_params


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None,
                 description: list[tuple[str, ...]] | None = None,
                 rowcount: int = 0) -> None:
        self._rows = rows or []
        self.description = description
        self.rowcount = rowcount
        self.executed: list[tuple[str, Any]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        pass

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


def test_select_returns_rows_as_dicts() -> None:
    cur = _FakeCursor(rows=[(1, "a"), (2, "b")], description=[("id",), ("name",)])
    conn = _FakeConn(cur)
    result = execute_with_params(conn, "SELECT id, name FROM t WHERE x = %s", (1,))
    assert result == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert cur.executed == [("SELECT id, name FROM t WHERE x = %s", (1,))]


def test_dml_returns_rowcount() -> None:
    cur = _FakeCursor(description=None, rowcount=3)
    conn = _FakeConn(cur)
    result = execute_with_params(
        conn, "UPDATE t SET x = %(x)s WHERE id = %(id)s", {"x": 5, "id": 1}
    )
    assert result == 3


def test_named_param_round_trips_through_driver() -> None:
    """`%(name)s` query round-trips through the (fake) psycopg2 driver.

    Asserts the three properties the chokepoint guarantees:
      (a) the SQL string is handed to ``cursor.execute`` UNMODIFIED — no
          pre-formatting, the ``%(name)s`` placeholder survives intact;
      (b) the params dict is passed through as the second arg, so the
          ``%(name)s`` binding happens at the driver, not via string ops;
      (c) the return value is derived from ``cursor.fetchall`` when the
          cursor exposes a ``description``.
    """
    sql = "SELECT id, name FROM t WHERE name = %(name)s"
    params = {"name": "robert'); DROP TABLE students;--"}
    canned_rows = [(1, "alice"), (2, "bob")]
    cur = _FakeCursor(rows=canned_rows, description=[("id",), ("name",)])
    conn = _FakeConn(cur)

    result = execute_with_params(conn, sql, params)

    # (a) SQL reached the driver byte-for-byte, placeholder intact.
    assert len(cur.executed) == 1
    sent_sql, sent_params = cur.executed[0]
    assert sent_sql == sql
    assert sent_sql is sql  # no copy / reformatting occurred
    assert "%(name)s" in sent_sql

    # (b) the params dict is forwarded verbatim as the bind map — the
    #     adversarial value is never spliced into the SQL text.
    assert sent_params is params
    assert sent_params == {"name": "robert'); DROP TABLE students;--"}
    assert "DROP TABLE" not in sent_sql

    # (c) returned rows are exactly the cursor's fetchall, keyed by the
    #     description columns.
    assert result == [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]


def test_named_param_returns_rowcount_when_no_description() -> None:
    """The same `%(name)s` binding path returns ``rowcount`` when the
    cursor has no ``description`` (a write, not a result set)."""
    sql = "UPDATE t SET flag = true WHERE name = %(name)s"
    params = {"name": "carol"}
    cur = _FakeCursor(description=None, rowcount=7)
    conn = _FakeConn(cur)

    result = execute_with_params(conn, sql, params)

    sent_sql, sent_params = cur.executed[0]
    assert sent_sql is sql  # unmodified
    assert sent_params is params  # passthrough
    assert result == 7  # rowcount when description is None


def test_no_params_path() -> None:
    cur = _FakeCursor(description=None, rowcount=0)
    conn = _FakeConn(cur)
    execute_with_params(conn, "BEGIN")
    assert cur.executed == [("BEGIN", None)] or cur.executed == [("BEGIN",)]


def test_rejects_non_string_sql() -> None:
    with pytest.raises(TypeError):
        execute_with_params(_FakeConn(_FakeCursor()), 123, ())  # type: ignore[arg-type]


def test_rejects_format_placeholder_with_params() -> None:
    with pytest.raises(UnsafeSqlError):
        execute_with_params(
            _FakeConn(_FakeCursor()),
            "SELECT * FROM t WHERE id = {id}",
            {"id": 1},
        )


def test_allows_format_placeholder_without_params() -> None:
    """f-string-shaped braces with no caller-supplied params are fine —
    the heuristic only fires when a binding map is present."""
    cur = _FakeCursor(description=None, rowcount=0)
    conn = _FakeConn(cur)
    execute_with_params(conn, "CREATE TABLE {auto_name} (id INT)")
    assert cur.executed[0][0].startswith("CREATE")


# ── run_cursor must stay silent ───────────────────────────────────────────────


def test_run_cursor_never_logs(caplog: pytest.LogCaptureFixture) -> None:
    """``run_cursor`` must not log its statement or its bound values.

    It is the single place every statement in the project is executed, so a
    convenience log line added here would emit every caller's parameters at
    once — including the password bound by ``setup_read_only_user``
    (``... IDENTIFIED BY %s``). This test fails if any logging is added, which
    is what makes the invariant in the module docstring enforceable rather than
    merely stated.
    """
    from src.admin_ops.db.cursor_exec import run_cursor

    secret = "correct-horse-battery-staple"  # nosec B105  # not a real credential
    cur = MagicMock()

    with caplog.at_level(logging.DEBUG):
        run_cursor(cur, "CREATE USER %s IDENTIFIED BY %s", ("reporting", secret))
        run_cursor(cur, "SELECT 1")

    assert caplog.records == [], (
        "run_cursor emitted log records; it must stay silent because every "
        "statement and bound value in the project passes through it."
    )
    # Belt and braces: the secret must not appear anywhere in captured output.
    assert secret not in caplog.text

    # The call still reached the driver, so the assertion above is meaningful.
    assert cur.execute.call_count == 2
    assert cur.execute.call_args_list[0].args[1] == ("reporting", secret)


def test_run_cursor_module_defines_no_logger() -> None:
    """No module-level logger in cursor_exec — the cheapest way to add logging.

    Catches the setup step before the log call itself, so the intent is blocked
    at the point someone reaches for ``logging.getLogger``.
    """
    import src.admin_ops.db.cursor_exec as mod

    loggers = [
        name
        for name, value in vars(mod).items()
        if isinstance(value, logging.Logger)
    ]
    assert loggers == [], f"cursor_exec must not hold a logger: {loggers}"
