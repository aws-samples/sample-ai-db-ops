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

"""Safe SQL identifier validation and quoting for DDL / administrative ops.

Parameter binding (see :mod:`src.admin_ops.db.execute`) protects *values*.
SQL *identifiers* — schema, table, index, column, role, view and parameter
names — cannot be bound as parameters by any of the drivers, so they must be
validated against a strict allowlist and quoted using the target engine's
native quoting rules before they are ever placed into a statement.

Using these helpers keeps caller-supplied identifiers from breaking out of
their lexical context (the classic ``users; DROP TABLE users; --`` payload).

Validates: requirements R7.6, R7.7 (no unbound caller input in SQL text).
"""

from __future__ import annotations

import re

# A conservative SQL identifier: a leading letter or underscore followed by up
# to 127 letters, digits, underscores or ``$``. This rejects whitespace,
# quotes, semicolons, comment markers, dots and every other character an
# attacker would need to escape the identifier context.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,127}$")

# Only these VACUUM / index options are ever emitted, so they are matched
# against fixed literals rather than interpolated from caller input.
_ALLOWED_MASKING_TYPES = frozenset({"partial", "full", "hash"})


class UnsafeIdentifierError(ValueError):
    """Raised when a caller-supplied identifier fails allowlist validation."""


def validate_identifier(name: str, *, kind: str = "identifier") -> str:
    """Return ``name`` unchanged if it is a safe SQL identifier, else raise.

    Args:
        name: The candidate identifier (schema, table, index, column, ...).
        kind: Human-readable label used in the error message.

    Raises:
        UnsafeIdentifierError: If ``name`` is not a plain, safe identifier.
    """
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise UnsafeIdentifierError(
            f"Invalid {kind}: {name!r}. Identifiers must match "
            f"[A-Za-z_][A-Za-z0-9_$]* and contain no quotes, whitespace, "
            f"dots or semicolons."
        )
    return name


def validate_column_list(columns) -> list[str]:
    """Validate an iterable (or comma-separated string) of column names."""
    if isinstance(columns, str):
        items = [c.strip() for c in columns.split(",") if c.strip()]
    else:
        items = [str(c).strip() for c in columns]
    if not items:
        raise UnsafeIdentifierError("At least one column is required.")
    return [validate_identifier(c, kind="column") for c in items]


def quote_mysql(name: str, *, kind: str = "identifier") -> str:
    """Validate then backtick-quote a MySQL identifier."""
    return "`" + validate_identifier(name, kind=kind) + "`"


def quote_oracle(name: str, *, kind: str = "identifier") -> str:
    """Validate then double-quote an (upper-cased) Oracle identifier."""
    return '"' + validate_identifier(name, kind=kind).upper() + '"'


def quote_mssql(name: str, *, kind: str = "identifier") -> str:
    """Validate then bracket-quote a SQL Server identifier.

    ``validate_identifier`` already rejects ``]``, so the closing bracket
    cannot be terminated early. Case is preserved because SQL Server
    identifiers are case-sensitive under a case-sensitive collation.
    """
    return "[" + validate_identifier(name, kind=kind) + "]"


def validate_masking_type(masking_type: str) -> str:
    """Validate a data-masking strategy against the fixed allowlist."""
    if masking_type not in _ALLOWED_MASKING_TYPES:
        raise UnsafeIdentifierError(
            f"Invalid masking_type: {masking_type!r}. "
            f"Expected one of {sorted(_ALLOWED_MASKING_TYPES)}."
        )
    return masking_type
