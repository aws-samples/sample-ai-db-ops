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

"""Builders for the few statements that cannot be parameterised.

Almost every statement in this project binds its values as parameters, and
:mod:`src.admin_ops.db.identifiers` covers the identifiers that binding cannot
reach. A small number of administrative statements fit neither rule, because
the engine's grammar does not accept a placeholder in the position concerned:

* MySQL ``KILL <id>`` takes a literal connection id, not a placeholder.
* Oracle ``ALTER SYSTEM KILL SESSION 'sid,serial'`` takes a literal string.
* DDL such as ``CREATE INDEX`` names identifiers, which are never bindable.
* ``EXPLAIN <statement>`` takes the analysed statement as part of the command
  rather than as a value, so it cannot be bound either.

Those statements are built **here and nowhere else**. Centralising them means
the validation cannot be forgotten at a call site, and a reader copying a call
gets the validation with it. Each builder narrows its input to a type that
cannot carry SQL text — an ``int`` for an id, a validated-and-quoted identifier
for a name — so the returned string is safe by construction rather than by
convention.

The rule for adding to this module: only for a position the engine genuinely
cannot bind. If a value can be a parameter, it must be a parameter.
"""

from __future__ import annotations

from src.admin_ops.admin.sql.classifier import classify
from src.admin_ops.db.identifiers import (
    UnsafeIdentifierError,
    quote_mysql,
    validate_column_list,
)
from src.admin_ops.db.sql_guard import assert_executable

# Session ids are positive and comfortably inside a 64-bit range on every
# engine here. Bounding them keeps a nonsense value from reaching the server.
_MAX_SESSION_ID = 2**63 - 1


def _session_id(value: object, *, name: str) -> int:
    """Coerce ``value`` to a bounded positive int, or raise.

    Returning an ``int`` is what makes the callers safe: an integer has no
    textual representation that could terminate a SQL statement or start a
    comment, so the result can be placed into SQL directly.
    """
    if isinstance(value, bool):
        raise UnsafeIdentifierError(f"{name} must be an integer, not a bool.")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise UnsafeIdentifierError(
            f"Invalid {name}: {value!r}. Must be an integer."
        ) from None
    if parsed <= 0 or parsed > _MAX_SESSION_ID:
        raise UnsafeIdentifierError(
            f"Invalid {name}: {parsed}. Must be between 1 and {_MAX_SESSION_ID}."
        )
    return parsed


def mysql_kill(connection_id: object) -> str:
    """Return a MySQL ``KILL`` statement for a validated connection id.

    MySQL does not accept a placeholder for the connection id, so the value is
    validated to a bounded positive integer and then rendered. Because the
    result of :func:`_session_id` is an ``int``, the interpolated text can only
    ever be digits.
    """
    return f"KILL {_session_id(connection_id, name='connection_id')}"


def oracle_kill_session(sid: object, serial: object) -> str:
    """Return an Oracle ``ALTER SYSTEM KILL SESSION`` statement.

    Oracle takes the session as a quoted ``'sid,serial'`` literal rather than
    bindable parameters. Both components are validated to bounded positive
    integers first, so the quoted literal cannot be closed early.
    """
    validated_sid = _session_id(sid, name="sid")
    validated_serial = _session_id(serial, name="serial")
    return (
        f"ALTER SYSTEM KILL SESSION '{validated_sid},{validated_serial}' IMMEDIATE"
    )


def mysql_create_index(
    index_name: str,
    table_name: str,
    columns: object,
    *,
    inplace: bool = False,
) -> str:
    """Return a MySQL ``CREATE INDEX`` / ``ALTER TABLE ... ADD INDEX`` statement.

    DDL names identifiers, which no driver can bind. Every identifier is
    validated against a strict allowlist and backtick-quoted by
    :func:`~src.admin_ops.db.identifiers.quote_mysql` before it reaches the
    statement, and that happens here so a caller cannot skip it.

    Args:
        index_name: Name for the new index.
        table_name: Table to index.
        columns: Column names, as a list or a comma-separated string.
        inplace: Emit the ``ALTER TABLE`` form with ``ALGORITHM=INPLACE,
            LOCK=NONE``, which avoids blocking writes on a large table.

    Returns:
        The DDL statement, safe to execute as-is.
    """
    quoted_index = quote_mysql(index_name, kind="index")
    quoted_table = quote_mysql(table_name, kind="table")
    quoted_columns = ", ".join(
        quote_mysql(c, kind="column") for c in validate_column_list(columns)
    )
    if inplace:
        return (
            f"ALTER TABLE {quoted_table} ADD INDEX {quoted_index} "
            f"({quoted_columns}), ALGORITHM=INPLACE, LOCK=NONE"
        )
    return f"CREATE INDEX {quoted_index} ON {quoted_table} ({quoted_columns})"


# Complete, static statements selected by an internal boolean. Held as whole
# strings so that no SQL text is assembled at runtime: the caller picks a
# statement, it does not build one. ``pid`` is bound as a parameter.
POSTGRES_CANCEL_BACKEND = "SELECT pg_cancel_backend(%s);"
POSTGRES_TERMINATE_BACKEND = "SELECT pg_terminate_backend(%s);"


def postgres_kill_backend(*, terminate: bool) -> str:
    """Return the PostgreSQL backend cancel or terminate statement.

    Both forms are full literals; ``terminate`` only chooses between them. The
    process id is passed separately as a bound parameter.
    """
    return POSTGRES_TERMINATE_BACKEND if terminate else POSTGRES_CANCEL_BACKEND


# ``EXPLAIN`` prefixes, by engine family. The analysed statement is appended by
# :func:`explain_read_only` and only after it has passed both controls, so the
# prefixes are never combined with unvalidated text.
_EXPLAIN_PREFIXES = {
    # EXPLAIN without ANALYZE: the statement is planned, never executed.
    "postgresql": "EXPLAIN (FORMAT JSON, COSTS, VERBOSE) ",
    "mysql": "EXPLAIN FORMAT=JSON ",
}


def explain_engine_family(engine: str) -> str | None:
    """Return the ``EXPLAIN`` engine family for ``engine``, or ``None``.

    ``None`` means this project has no ``EXPLAIN`` form for the engine, which
    callers report rather than guessing at a syntax.
    """
    for family in _EXPLAIN_PREFIXES:
        if family in engine:
            return family
    return None


def explain_read_only(engine: str, query_text: str) -> str:
    """Validate ``query_text`` as a read and return the ``EXPLAIN`` statement.

    Validation and prefixing are deliberately the *same* call. ``EXPLAIN`` is
    the one place in this project where caller-supplied SQL text has to be
    concatenated into a command, and the safety of doing so rests entirely on
    the two checks below. Splitting them from the concatenation would leave a
    snippet that looks reusable but is only safe in context — so this function
    is the only place the prefix is applied, and it refuses anything it has not
    itself verified.

    The checks are:

    1. :func:`~src.admin_ops.db.sql_guard.assert_executable` rejects stacked
       statements and constructs that reach outside the database
       (``COPY ... PROGRAM``, ``UTL_FILE`` and similar).
    2. :func:`~src.admin_ops.admin.sql.classifier.classify` must return
       ``tier_1_read``. For PostgreSQL this parses the statement with pglast
       and inspects the node type; it fails closed to ``tier_3_act`` on any
       parse error or unrecognised keyword.

    A prefix check is deliberately *not* used: ``SELECT`` alone admits UNIONs
    and subqueries against unrelated tables.

    Args:
        engine: Registry engine value, e.g. ``aurora-postgresql``.
        query_text: The statement to be explained.

    Returns:
        A complete ``EXPLAIN`` statement, safe to execute as-is.

    Raises:
        ValueError: If the engine has no ``EXPLAIN`` form here, if the
            statement is not a single statement, or if it is not classified as
            a read. :class:`~src.admin_ops.db.sql_guard.BlockedSqlError` (a
            ``ValueError`` subclass) is raised for constructs that reach
            outside the database.
    """
    family = explain_engine_family(engine)
    if family is None:
        raise ValueError(f"No EXPLAIN form defined for engine: {engine}")

    stripped = query_text.strip().rstrip(";").strip()
    assert_executable(stripped)

    classification = classify(family, stripped)
    if classification.tier != "tier_1_read":
        raise ValueError(
            f"query_text must be a read-only statement; classified as "
            f"{classification.tier} ({classification.reason}). "
            f"Only SELECT/WITH-style reads can be explained by this tool."
        )

    return _EXPLAIN_PREFIXES[family] + stripped
