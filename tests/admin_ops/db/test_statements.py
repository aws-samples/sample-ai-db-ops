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

"""Builders for statements the engines cannot parameterise.

These are the only places SQL text is assembled from input, so the tests here
are about one property: nothing a caller supplies can escape its position.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from src.admin_ops.db import statements
from src.admin_ops.db.identifiers import UnsafeIdentifierError
from src.admin_ops.db.statements import (
    mysql_create_index,
    mysql_kill,
    oracle_kill_session,
    postgres_kill_backend,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# Payloads that would break out of the statement if the value were interpolated
# without validation.
INJECTION_PAYLOADS = [
    "1; DROP TABLE users",
    "1' OR '1'='1",
    "1 -- comment",
    "1/*comment*/",
    "1\nDROP TABLE users",
    "' IMMEDIATE; ALTER SYSTEM CHECKPOINT --",
    "0x01",
    "1e5",
    "",
    "   ",
    None,
    [],
    {},
]


# ── Session ids reduce to digits or raise ────────────────────────────────────


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_mysql_kill_rejects_non_integers(payload):
    with pytest.raises(UnsafeIdentifierError):
        mysql_kill(payload)


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_oracle_kill_rejects_non_integers(payload):
    with pytest.raises(UnsafeIdentifierError):
        oracle_kill_session(payload, 1)
    with pytest.raises(UnsafeIdentifierError):
        oracle_kill_session(1, payload)


@pytest.mark.parametrize("bad", [0, -1, 2**63])
def test_session_ids_must_be_positive_and_bounded(bad):
    with pytest.raises(UnsafeIdentifierError):
        mysql_kill(bad)


def test_bool_is_not_an_acceptable_session_id():
    """``True`` is an int in Python, but it is never a real session id."""
    with pytest.raises(UnsafeIdentifierError):
        mysql_kill(True)


def test_mysql_kill_emits_only_digits():
    assert mysql_kill(42) == "KILL 42"
    assert mysql_kill("42") == "KILL 42", "a numeric string is still a valid id"


def test_oracle_kill_session_shape():
    stmt = oracle_kill_session(12, 345)
    assert stmt == "ALTER SYSTEM KILL SESSION '12,345' IMMEDIATE"
    # The quoted literal is closed exactly once, so nothing follows IMMEDIATE.
    assert stmt.count("'") == 2


# ── PostgreSQL statements are whole literals, not assembled ─────────────────


def test_postgres_kill_backend_returns_complete_statements():
    assert postgres_kill_backend(terminate=False) == "SELECT pg_cancel_backend(%s);"
    assert postgres_kill_backend(terminate=True) == "SELECT pg_terminate_backend(%s);"


def test_postgres_kill_backend_keeps_pid_bindable():
    """The pid must stay a placeholder so it is bound, never interpolated."""
    for terminate in (True, False):
        assert postgres_kill_backend(terminate=terminate).count("%s") == 1


# ── DDL identifiers are validated and quoted ────────────────────────────────


def test_mysql_create_index_quotes_every_identifier():
    ddl = mysql_create_index("idx_email", "customers", ["email", "created_at"])
    assert ddl == (
        "CREATE INDEX `idx_email` ON `customers` (`email`, `created_at`)"
    )


def test_mysql_create_index_inplace_form():
    ddl = mysql_create_index("idx_a", "t", "a", inplace=True)
    assert ddl == (
        "ALTER TABLE `t` ADD INDEX `idx_a` (`a`), ALGORITHM=INPLACE, LOCK=NONE"
    )


@pytest.mark.parametrize(
    "index_name,table_name,columns",
    [
        ("idx`; DROP TABLE t; --", "t", ["a"]),
        ("idx", "t`; DROP TABLE t; --", ["a"]),
        ("idx", "t", ["a`, (SELECT 1)"]),
        ("idx", "t", ["a; DROP TABLE t"]),
        ("idx", "t", []),
        ("", "t", ["a"]),
    ],
)
def test_mysql_create_index_rejects_unsafe_identifiers(index_name, table_name, columns):
    with pytest.raises(UnsafeIdentifierError):
        mysql_create_index(index_name, table_name, columns)


def test_mysql_create_index_accepts_comma_separated_columns():
    ddl = mysql_create_index("i", "t", "a, b")
    assert "(`a`, `b`)" in ddl


# ── The builders are the only place these statements are written ─────────────


# Statement heads that must only ever be written inside statements.py.
_GUARDED_HEADS = ("KILL ", "ALTER SYSTEM KILL SESSION", "EXPLAIN ")


def test_no_call_site_assembles_these_statements_itself():
    """Drift guard: these statement texts belong in one module.

    Catches a future change that reintroduces an inline ``f"KILL {pid}"`` or
    ``"EXPLAIN " + sql`` rather than calling the validated builder. ``EXPLAIN``
    is included because it is the one place caller-supplied SQL text has to be
    concatenated, and its safety depends entirely on the validation that
    :func:`explain_read_only` performs in the same call.
    """
    offenders: list[str] = []
    for path in sorted(REPO_ROOT.glob("**/*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith((".venv/", "tests/", "build/")) or "__pycache__" in rel:
            continue
        if rel == "src/admin_ops/db/statements.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            # An f-string, a %-format, or a `"..." + x` concatenation whose text
            # starts one of the guarded statements.
            if isinstance(node, ast.JoinedStr):
                head = next(
                    (
                        v.value
                        for v in node.values
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)
                    ),
                    "",
                )
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
                head = node.left.value if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str) else ""
            else:
                continue
            # Only leading whitespace is stripped: the guarded heads end in a
            # space to force a token boundary, so stripping the trailing space
            # here would stop `"EXPLAIN " + sql` from ever matching.
            upper = head.upper().lstrip()
            if any(upper.startswith(h) for h in _GUARDED_HEADS):
                offenders.append(f"{rel}:{node.lineno}  ({head.strip()[:40]!r})")
    assert not offenders, (
        "These statements must be built by src/admin_ops/db/statements.py so the "
        "validation cannot be skipped:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    "source",
    [
        'explain = "EXPLAIN " + user_sql\n',
        'explain = "EXPLAIN FORMAT=JSON " + user_sql\n',
        'stmt = f"KILL {pid}"\n',
        'stmt = "KILL %d" % pid\n',
        'stmt = f"ALTER SYSTEM KILL SESSION \'{sid},{serial}\' IMMEDIATE"\n',
    ],
)
def test_drift_guard_detects_the_patterns_it_claims_to(source):
    """The guard must actually fire on these shapes — otherwise it proves nothing.

    This mirrors the matching logic in the guard above against known-offending
    source, so a refactor that silently stops matching fails here rather than
    passing a scan by accident.
    """
    matched = False
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.JoinedStr):
            head = next(
                (
                    v.value
                    for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                ),
                "",
            )
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
            head = node.left.value if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str) else ""
        else:
            continue
        if any(head.upper().lstrip().startswith(h) for h in _GUARDED_HEADS):
            matched = True
    assert matched, f"Guard would not catch: {source!r}"


# ── EXPLAIN is validated and prefixed in the same call ────────────────────────


@pytest.mark.parametrize(
    "engine,expected",
    [
        ("aurora-postgresql", "postgresql"),
        ("postgresql", "postgresql"),
        ("aurora-mysql", "mysql"),
        ("mysql", "mysql"),
        ("oracle", None),
        ("dynamodb", None),
        ("", None),
    ],
)
def test_explain_engine_family(engine, expected):
    assert statements.explain_engine_family(engine) == expected


def test_explain_read_only_prefixes_postgres_without_analyze():
    sql = statements.explain_read_only("aurora-postgresql", "SELECT 1")
    assert sql == "EXPLAIN (FORMAT JSON, COSTS, VERBOSE) SELECT 1"
    # ANALYZE would execute the statement rather than plan it.
    assert "ANALYZE" not in sql.upper()


def test_explain_read_only_prefixes_mysql():
    assert (
        statements.explain_read_only("aurora-mysql", "SELECT a FROM t")
        == "EXPLAIN FORMAT=JSON SELECT a FROM t"
    )


def test_explain_read_only_strips_trailing_semicolon_and_whitespace():
    assert (
        statements.explain_read_only("aurora-mysql", "  SELECT 1 ;  ")
        == "EXPLAIN FORMAT=JSON SELECT 1"
    )


def test_explain_read_only_refuses_unsupported_engine():
    with pytest.raises(ValueError, match="No EXPLAIN form"):
        statements.explain_read_only("oracle", "SELECT 1")


@pytest.mark.parametrize(
    "payload",
    [
        "DROP TABLE customers",
        "UPDATE customers SET name = 'x'",
        "DELETE FROM customers",
        "TRUNCATE customers",
        "INSERT INTO customers VALUES (1)",
        "SELECT 1; DROP TABLE customers",
        "GRANT ALL ON customers TO attacker",
        "ALTER TABLE customers ADD COLUMN x int",
        "CREATE TABLE t (a int)",
    ],
)
def test_explain_read_only_refuses_anything_not_a_verified_read(payload):
    """A non-read must never reach the prefix, on either engine."""
    for engine in ("aurora-postgresql", "aurora-mysql"):
        with pytest.raises(ValueError):
            statements.explain_read_only(engine, payload)


@pytest.mark.parametrize(
    "payload",
    [
        "COPY customers FROM PROGRAM 'sh -c id'",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT lo_import('/etc/passwd')",
    ],
)
def test_explain_read_only_refuses_statements_that_leave_the_database(payload):
    with pytest.raises(ValueError):
        statements.explain_read_only("aurora-postgresql", payload)


def test_explain_read_only_accepts_a_read_with_a_trailing_comment():
    """`SELECT 1 -- ; DROP TABLE x` is a single read, and is correctly allowed.

    Recorded deliberately: the text after ``--`` is a comment, so the server
    only ever plans ``SELECT 1``. Refusing it would be a false rejection, and
    asserting it is refused would bake in a misunderstanding of the guard.
    """
    sql = statements.explain_read_only(
        "aurora-postgresql", "SELECT 1 -- ; DROP TABLE customers"
    )
    assert sql.startswith("EXPLAIN (FORMAT JSON, COSTS, VERBOSE) SELECT 1")
    # The DROP remains inert: it is inside the comment, not a second statement.
    assert "--" in sql
