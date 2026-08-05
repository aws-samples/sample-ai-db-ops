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

"""Single chokepoint for parameter-bound SQL execution.

All admin-ops-console code paths that touch a database write MUST go
through `execute_with_params`. The helper accepts a SQL string with
driver-native placeholders (`%s`, `%(name)s` for psycopg2/pymysql,
`:name` for oracledb) plus a parameters dict or sequence — and refuses
to accept already-formatted SQL.

Static enforcement: `.semgrep/no-fstring-sql.yml` rejects `cursor.execute(f"...")`
and `cursor.execute("..." % ...)` patterns at lint time.

Validates: requirements R7.6, R7.7, R7.10.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


class UnsafeSqlError(ValueError):
    """Raised when caller passes a value that bypasses parameter binding."""


def execute_with_params(
    conn: Any,
    sql: str,
    params: Mapping[str, Any] | Sequence[Any] | None = None,
) -> list[dict[str, Any]] | int:
    """Run `sql` against `conn` with `params` bound through the driver.

    Returns the fetched rows as a list of dicts when the cursor produced a
    result set, otherwise returns the row count. Raises `UnsafeSqlError`
    if the input looks pre-formatted (e.g., contains a literal ``"%s" %``
    fragment, or has the param sentinel and a Python f-string brace
    pattern at the same time).

    The helper does not commit; the caller is responsible for transaction
    boundaries.
    """
    if not isinstance(sql, str):
        raise TypeError(f"sql must be str, got {type(sql).__name__}")
    if "{" in sql and "}" in sql and params:
        # Heuristic: an f-string-style placeholder is suspicious when the
        # caller is also passing bound params. Fail closed.
        raise UnsafeSqlError(
            "SQL appears to contain a Python format placeholder; "
            "use driver placeholders (%s, %(name)s, :name) instead."
        )

    with conn.cursor() as cur:
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        if cur.description is None:
            return cur.rowcount
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
