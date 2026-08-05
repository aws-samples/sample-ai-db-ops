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

"""Hard blocks for SQL constructs that escape the database boundary.

The Tier-3 approval hook (:mod:`src.hooks.tier3_approval`) makes every mutating
tool call subject to human approval. This module is the layer underneath that:
constructs which break out of the database into the host OS, the filesystem, or
the network are refused outright, because no operator approval prompt conveys
what they actually do. An operator approving "run this SQL" is not meaningfully
consenting to shell execution on the database host.

Blocked categories
------------------

* **Command execution** — ``COPY … FROM/TO PROGRAM`` (PostgreSQL),
  ``xp_cmdshell``, Oracle ``DBMS_SCHEDULER`` / ``DBMS_JAVA``.
* **Filesystem access** — ``pg_read_file``, ``lo_import``/``lo_export``,
  MySQL ``LOAD_FILE`` / ``INTO OUTFILE`` / ``INTO DUMPFILE`` / ``LOAD DATA …
  INFILE``, Oracle ``UTL_FILE`` and ``CREATE DIRECTORY``.
* **Outbound network access** — Oracle ``UTL_HTTP`` / ``UTL_TCP`` / ``UTL_SMTP``
  / ``UTL_INADDR``, PostgreSQL ``dblink`` and ``postgres_fdw`` (SSRF and data
  exfiltration paths).
* **Engine reconfiguration and native code loading** — ``ALTER SYSTEM``,
  ``CREATE EXTENSION``.

Matching is intentionally conservative
--------------------------------------

Detection runs on the statement with comments removed, using word-boundary
matching, and does **not** try to exclude string literals. A statement that
merely mentions a blocked token inside a literal is therefore rejected. That is
the deliberate direction to err in: a false rejection is a usability
annoyance, while a false acceptance is a host compromise. Callers that need to
store such text should use a parameterized insert, where the value travels as a
bound parameter and never appears in the statement text.
"""

from __future__ import annotations

import re

# Comment stripping mirrors the SQL classifier so both see the same statement.
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")

# Each entry: (human-readable label, compiled pattern).
_BLOCKED: tuple[tuple[str, re.Pattern[str]], ...] = (
    # ── Command execution ───────────────────────────────────────────────────
    ("COPY ... PROGRAM (host command execution)", re.compile(r"\bCOPY\b[\s\S]*?\bPROGRAM\b", re.I)),
    ("xp_cmdshell (host command execution)", re.compile(r"\bxp_cmdshell\b", re.I)),
    ("DBMS_SCHEDULER (host command execution)", re.compile(r"\bDBMS_SCHEDULER\b", re.I)),
    ("DBMS_JAVA (host command execution)", re.compile(r"\bDBMS_JAVA\b", re.I)),
    ("DBMS_CREDENTIAL (stored OS credentials)", re.compile(r"\bDBMS_CREDENTIAL\b", re.I)),
    # ── Filesystem access ───────────────────────────────────────────────────
    ("pg_read_file / pg_read_binary_file (filesystem read)", re.compile(r"\bpg_read(_binary)?_file\b", re.I)),
    ("pg_ls_dir (filesystem listing)", re.compile(r"\bpg_ls_dir\b", re.I)),
    ("pg_file_write / pg_file_unlink (filesystem write)", re.compile(r"\bpg_file_(write|unlink|rename)\b", re.I)),
    ("lo_import / lo_export (filesystem access)", re.compile(r"\blo_(import|export)\b", re.I)),
    ("LOAD_FILE (filesystem read)", re.compile(r"\bLOAD_FILE\s*\(", re.I)),
    ("INTO OUTFILE / DUMPFILE (filesystem write)", re.compile(r"\bINTO\s+(OUT|DUMP)FILE\b", re.I)),
    ("LOAD DATA ... INFILE (filesystem read)", re.compile(r"\bLOAD\s+DATA\b[\s\S]*?\bINFILE\b", re.I)),
    ("UTL_FILE (filesystem access)", re.compile(r"\bUTL_FILE\b", re.I)),
    ("CREATE DIRECTORY (filesystem mapping)", re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?DIRECTORY\b", re.I)),
    ("DBMS_LOB.LOADFROMFILE (filesystem read)", re.compile(r"\bDBMS_LOB\s*\.\s*LOADFROMFILE\b", re.I)),
    # ── Outbound network access ─────────────────────────────────────────────
    ("UTL_HTTP (outbound network access)", re.compile(r"\bUTL_HTTP\b", re.I)),
    ("UTL_TCP (outbound network access)", re.compile(r"\bUTL_TCP\b", re.I)),
    ("UTL_SMTP (outbound network access)", re.compile(r"\bUTL_SMTP\b", re.I)),
    ("UTL_INADDR (outbound network access)", re.compile(r"\bUTL_INADDR\b", re.I)),
    ("dblink (outbound network access)", re.compile(r"\bdblink(_connect|_exec|_open)?\s*\(", re.I)),
    ("postgres_fdw / dblink extension (outbound network access)", re.compile(r"\bpostgres_fdw\b", re.I)),
    # ── Engine reconfiguration / native code ────────────────────────────────
    ("ALTER SYSTEM (engine reconfiguration)", re.compile(r"\bALTER\s+SYSTEM\b", re.I)),
    ("CREATE EXTENSION (loads native code)", re.compile(r"\bCREATE\s+EXTENSION\b", re.I)),
)


class BlockedSqlError(ValueError):
    """Raised when a statement contains a construct that is never permitted."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Statement rejected: {reason}. This construct reaches outside the "
            f"database and is blocked by policy; it cannot be enabled by approval."
        )
        self.reason = reason


def strip_comments(sql: str) -> str:
    """Remove block and line comments from ``sql``."""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub(" ", sql))


def find_blocked_construct(sql: str) -> str | None:
    """Return a label for the first blocked construct found, else ``None``."""
    if not isinstance(sql, str) or not sql.strip():
        return None
    cleaned = strip_comments(sql)
    for label, pattern in _BLOCKED:
        if pattern.search(cleaned):
            return label
    return None


def assert_sql_allowed(sql: str) -> None:
    """Raise :class:`BlockedSqlError` if ``sql`` contains a blocked construct."""
    reason = find_blocked_construct(sql)
    if reason is not None:
        raise BlockedSqlError(reason)


def assert_single_statement(sql: str) -> None:
    """Raise ``ValueError`` when more than one statement is supplied.

    Stacked statements let a single approved operation smuggle in a second,
    unapproved one, so they are refused before the approval fingerprint is
    ever computed.
    """
    if not isinstance(sql, str):
        raise ValueError("SQL statement must be a string.")
    stmt = strip_comments(sql).rstrip()
    while stmt.endswith(";"):
        stmt = stmt[:-1].rstrip()
    if ";" in stmt:
        raise ValueError("Multiple SQL statements are not permitted.")


def assert_executable(sql: str) -> None:
    """Full pre-execution check: single statement, no blocked constructs."""
    assert_single_statement(sql)
    assert_sql_allowed(sql)
