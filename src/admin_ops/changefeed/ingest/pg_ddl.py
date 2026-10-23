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

"""PostgreSQL DDL ingester for the Change Feed (`database` source).

Captures live schema changes (ALTER / TRUNCATE / CREATE / DROP / etc.)
executed against the database itself -- not code, not infra-as-code, but
the actual DDL run on the live cluster. This complements the `git`
source: git tells you what changed in the repo; this tells you what
changed in the database.

How it is fed
-------------
1. The cluster parameter group sets ``log_statement = 'ddl'`` (or
   ``'mod'`` / ``'all'``), so Postgres writes every DDL statement to its
   log.
2. Aurora exports the ``postgresql`` log group to CloudWatch Logs.
3. A CloudWatch Logs subscription filter streams those log events to a
   Lambda, which calls :func:`ingest_log_event` for each record.

This module parses the Postgres log line, extracts the DDL verb and the
target object, classifies severity, and writes a ChangeEvent. Parsing is
defensive: a line that does not look like a DDL statement log is skipped
(returns None), and a malformed record never halts the stream (R4.9).

The module is import-safe without AWS -- it only touches the change-feed
store, whose dev backend is a local JSON file.

Validates: R4.4 (live DB change capture), R4.7, R4.9.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
from src.admin_ops.errors import redact
from src.admin_ops.changefeed import store

LOG = logging.getLogger(__name__)

# DDL verbs we recognise. Maps the leading token(s) to a severity.
# TRUNCATE and DROP are the most destructive -> high. ALTER -> high
# (schema change). CREATE -> medium. Everything else mapped here -> medium.
_DDL_SEVERITY: dict[str, str] = {
    "DROP": "high",
    "TRUNCATE": "high",
    "ALTER": "high",
    "CREATE": "medium",
    "COMMENT": "low",
    "GRANT": "high",
    "REVOKE": "high",
    "RENAME": "high",
    "REINDEX": "medium",
    "CLUSTER": "medium",
    "REFRESH": "low",
}

# A Postgres log line for a logged statement looks roughly like:
#   2026-06-02 15:30:01 UTC:10.0.5.1(54321):appuser@appdb:[1234]:LOG:
#   statement: ALTER TABLE shop.orders ADD COLUMN note text;
# Aurora's CloudWatch records vary, so we parse loosely: find the
# "statement:" / "execute <name>:" marker and take what follows.
_STMT_RE = re.compile(
    r"(?:statement|execute\s+[^:]*):\s*(?P<sql>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)

# Pull user@db out of the log prefix when present: "user@db:"
_USER_DB_RE = re.compile(r"(?P<user>[A-Za-z0-9_]+)@(?P<db>[A-Za-z0-9_]+):")

# Leading DDL verb + best-effort object name.
_DDL_HEAD_RE = re.compile(
    r"^\s*(?P<verb>[A-Za-z]+)\s+"
    r"(?:(?P<obj_kind>TABLE|INDEX|VIEW|MATERIALIZED\s+VIEW|SCHEMA|SEQUENCE|"
    r"FUNCTION|TRIGGER|TYPE|ROLE|USER|DATABASE|EXTENSION|CONSTRAINT)\s+)?"
    r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
    r"(?P<name>[A-Za-z0-9_\.\"]+)?",
    re.IGNORECASE,
)

# Statements that are technically logged under log_statement=ddl/mod but
# are not schema changes we care to surface.
_IGNORE_VERBS = {"SET", "SHOW", "BEGIN", "COMMIT", "ROLLBACK"}


def _is_ddl(sql: str) -> bool:
    head = sql.strip().split(None, 1)
    if not head:
        return False
    return head[0].upper() in _DDL_SEVERITY


def _classify(sql: str) -> tuple[str, str, str] | None:
    """Return (verb, severity, object_name) for a DDL statement, or None."""
    m = _DDL_HEAD_RE.match(sql.strip())
    if not m:
        return None
    verb = (m.group("verb") or "").upper()
    if verb in _IGNORE_VERBS or verb not in _DDL_SEVERITY:
        return None
    severity = _DDL_SEVERITY[verb]
    obj_kind = (m.group("obj_kind") or "").strip()
    name = (m.group("name") or "").strip().strip('"')
    obj = f"{obj_kind} {name}".strip() if obj_kind else name
    return verb, severity, (obj or "?")


def parse_pg_log_message(message: str) -> dict[str, Any] | None:
    """Parse one Postgres log line into a structured DDL record.

    Returns a dict with keys ``sql``, ``verb``, ``severity``, ``object``,
    ``actor`` (user@db or "postgres"), or None if the line is not a DDL
    statement we track.
    """
    if not message:
        return None
    stmt = _STMT_RE.search(message)
    if not stmt:
        return None
    sql = stmt.group("sql").strip().rstrip(";").strip()
    if not _is_ddl(sql):
        return None
    classified = _classify(sql)
    if classified is None:
        return None
    verb, severity, obj = classified

    actor = "postgres"
    ud = _USER_DB_RE.search(message)
    if ud:
        actor = f"{ud.group('user')}@{ud.group('db')}"

    return {
        "sql": sql,
        "verb": verb,
        "severity": severity,
        "object": obj,
        "actor": actor,
    }


def _event_from_record(
    *,
    message: str,
    timestamp_ms: int | None,
    db_identifier: str,
    log_stream: str | None,
) -> ChangeEvent | None:
    parsed = parse_pg_log_message(message)
    if parsed is None:
        return None

    if timestamp_ms is not None:
        ts = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    actor = parsed["actor"][:128]
    obj = parsed["object"]
    verb = parsed["verb"]
    resource_id = f"pg_ddl:{db_identifier}:{obj}"[:256]
    # DDL such as CREATE ROLE ... PASSWORD '...' can carry credentials, and the
    # summary is persisted and shown in the UI, so strip quoted literals and
    # key=value secrets before storing a preview.
    sql_preview = redact(parsed["sql"], max_len=300)
    summary = f"{verb} on {obj} ({db_identifier}): {sql_preview}"[:512]

    # CloudWatch Logs Insights deep-link is derived at the UI layer from
    # runtime config; here we record a stable, id-free reference.
    details_url = f"cloudwatch:postgresql:{db_identifier}"
    raw_ref = f"pgddl:{log_stream or 'stream'}:{int(ts.timestamp())}"

    return ChangeEvent(
        event_id=make_event_id("database", actor, ts, resource_id),
        source="database",
        actor=actor,
        timestamp=ts,
        engine="postgresql",
        resource_id=resource_id,
        severity=parsed["severity"],  # type: ignore[arg-type]
        summary=summary,
        details_url=details_url[:2048],
        raw_payload_ref=raw_ref[:512],
    )


def ingest_log_event(
    *,
    message: str,
    timestamp_ms: int | None = None,
    db_identifier: str = "database-test",
    log_stream: str | None = None,
) -> bool:
    """Ingest a single Postgres log message. Returns True if an event was written."""
    try:
        event = _event_from_record(
            message=message,
            timestamp_ms=timestamp_ms,
            db_identifier=db_identifier,
            log_stream=log_stream,
        )
    except Exception as exc:  # noqa: BLE001 - one bad record never halts the stream (R4.9)
        LOG.warning("pg_ddl: failed to parse record: %s", exc)
        return False
    if event is None:
        return False
    try:
        return store.put_event(event)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("pg_ddl: failed to write event: %s", exc)
        return False


def handle_cloudwatch_logs_event(payload: Mapping[str, Any]) -> dict:
    """Entry point for a CloudWatch Logs subscription Lambda.

    `payload` is the already-decoded CloudWatch Logs data
    (``{"logGroup", "logStream", "logEvents": [{"timestamp", "message"}]}``).
    The Lambda wrapper is responsible for the gzip+base64 decode of
    `awslogs.data`; this function takes the decoded dict so it is unit
    testable without AWS.
    """
    db_identifier = _db_from_log_group(payload.get("logGroup", ""))
    log_stream = payload.get("logStream")
    events: Iterable[Mapping[str, Any]] = payload.get("logEvents", []) or []
    written = 0
    scanned = 0
    for ev in events:
        scanned += 1
        if ingest_log_event(
            message=str(ev.get("message", "")),
            timestamp_ms=ev.get("timestamp"),
            db_identifier=db_identifier,
            log_stream=log_stream,
        ):
            written += 1
    return {"scanned": scanned, "events_written": written, "db_identifier": db_identifier}


def _db_from_log_group(log_group: str) -> str:
    """Derive the db identifier from the CloudWatch log group name.

    Aurora writes to ``/aws/rds/cluster/<cluster-id>/postgresql``. We take
    the cluster id. Falls back to ``database-test`` for the demo.
    """
    m = re.search(r"/aws/rds/cluster/([^/]+)/postgresql", log_group)
    if m:
        return m.group(1)
    return "database-test"
