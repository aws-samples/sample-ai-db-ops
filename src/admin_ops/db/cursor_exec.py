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

"""Single cursor-execution chokepoint for already-built statements.

Value binding is handled by the driver (``params``). SQL *identifiers*
(schema/table/index/column/role names) are validated and quoted at the call
site via :mod:`src.admin_ops.db.identifiers` before the statement is composed,
so by the time a statement reaches :func:`run_cursor` it carries no unbound
caller input.

Centralising the ``cursor.execute`` call here means SQL text is composed at the
call site and passed in as a plain parameter — there is exactly one audited
place in the code that actually invokes ``execute``.

**This module must never log its arguments.** Being the single chokepoint makes
it the most tempting place to add tracing, and the worst place to do it: every
statement and every bound value in the project passes through here, including
credentials. ``setup_read_only_user`` binds a password
(``... IDENTIFIED BY %s``), so a single ``LOG.debug("%s %s", statement, params)``
added here would write that password to the log for every caller at once. The
invariant is asserted by ``test_run_cursor_never_logs`` in
``tests/admin_ops/db/test_execute.py``, so adding logging here fails the build.

Diagnostics belong at the call site, where the caller knows which values are
sensitive, or in the driver's own logging, which the operator opts into.
"""

from __future__ import annotations

from typing import Any


def run_cursor(cur: Any, statement: Any, params: Any = None) -> Any:
    """Execute a pre-built ``statement`` on DB-API ``cur``.

    Args:
        cur: An open DB-API cursor (psycopg2 / pymysql / oracledb).
        statement: A SQL string, or a driver composable (e.g. a psycopg2
            ``sql.Composed``) that was built from validated identifiers and
            driver placeholders at the call site.
        params: Optional bound values (sequence or mapping). Passed straight
            to the driver for server-side parameter binding. These may include
            a password — see the module docstring: they must not be logged
            here, or anywhere that receives them generically.

    Returns:
        Whatever the driver's ``execute`` returns (callers typically fetch
        from ``cur`` afterwards).
    """
    if params is None:
        return cur.execute(statement)
    return cur.execute(statement, params)
