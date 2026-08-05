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

"""Actioned operation tools — Tier 3 (requires approval before execution)."""

from strands import tool

from src.admin_ops.db.cursor_exec import run_cursor
from src.admin_ops.db.identifiers import (
    validate_column_list,
    validate_identifier,
)
from src.admin_ops.db.statements import (
    mysql_create_index,
    mysql_kill,
    postgres_kill_backend,
)
from src.tools._helpers import get_privileged_connection, get_registry_entry


@tool
def create_index(
    db_identifier: str,
    table_name: str,
    columns: list[str],
    index_name: str,
    schema_name: str = "public",
    concurrently: bool = True,
) -> dict:
    """Create an index on the specified table. Requires approval.

    This operation may take minutes to hours depending on table size.
    AgentCore Runtime supports sessions up to 8 hours — no timeout concern.

    Args:
        db_identifier: Target database identifier.
        table_name: Table to create the index on.
        columns: List of columns to include in the index.
        index_name: Name for the new index.
        schema_name: Schema name (default 'public').
        concurrently: Whether to create without locking (default True, recommended for production).

    Returns:
        A dict with the execution result and timing.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_privileged_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        from psycopg2 import sql

        cols = validate_column_list(columns)
        validate_identifier(index_name, kind="index")
        validate_identifier(schema_name, kind="schema")
        validate_identifier(table_name, kind="table")

        stmt = sql.SQL("CREATE INDEX {conc} {idx} ON {sch}.{tbl} ({cols})").format(
            conc=sql.SQL("CONCURRENTLY") if concurrently else sql.SQL(""),
            idx=sql.Identifier(index_name),
            sch=sql.Identifier(schema_name),
            tbl=sql.Identifier(table_name),
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
        )

        import time

        start = time.time()
        with conn.cursor() as cur:
            run_cursor(cur, stmt)
        elapsed = round(time.time() - start, 2)

        return {
            "db_identifier": db_identifier,
            "status": "completed",
            "index_name": index_name,
            "ddl_executed": stmt.as_string(conn),
            "duration_seconds": elapsed,
            "concurrently": concurrently,
        }

    elif "mysql" in engine:
        # DDL names identifiers, which no driver can bind. The builder validates
        # and backtick-quotes every identifier, so it cannot be skipped here.
        ddl = mysql_create_index(index_name, table_name, columns)

        import time

        start = time.time()
        with conn.cursor() as cur:
            run_cursor(cur, ddl)
        elapsed = round(time.time() - start, 2)

        return {
            "db_identifier": db_identifier,
            "status": "completed",
            "index_name": index_name,
            "ddl_executed": ddl,
            "duration_seconds": elapsed,
        }

    return {"error": f"create_index not implemented for engine: {engine}"}


@tool
def drop_index(
    db_identifier: str,
    index_name: str,
    schema_name: str = "public",
    concurrently: bool = True,
) -> dict:
    """Drop an unused index. Requires approval.

    Args:
        db_identifier: Target database identifier.
        index_name: Name of the index to drop.
        schema_name: Schema name (default 'public').
        concurrently: Whether to drop without locking (default True).

    Returns:
        A dict with the execution result.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_privileged_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        from psycopg2 import sql

        validate_identifier(index_name, kind="index")
        validate_identifier(schema_name, kind="schema")

        stmt = sql.SQL("DROP INDEX {conc} {sch}.{idx}").format(
            conc=sql.SQL("CONCURRENTLY") if concurrently else sql.SQL(""),
            sch=sql.Identifier(schema_name),
            idx=sql.Identifier(index_name),
        )

        with conn.cursor() as cur:
            run_cursor(cur, stmt)

        return {
            "db_identifier": db_identifier,
            "status": "completed",
            "index_dropped": index_name,
            "ddl_executed": stmt.as_string(conn),
        }

    return {"error": f"drop_index not implemented for engine: {engine}"}


@tool
def execute_vacuum(
    db_identifier: str,
    table_name: str,
    schema_name: str = "public",
    full: bool = False,
    analyze: bool = True,
) -> dict:
    """Execute VACUUM on a table. Requires approval.

    VACUUM FULL rewrites the entire table and requires an exclusive lock.
    Regular VACUUM can run concurrently with normal operations.

    Args:
        db_identifier: Target database identifier.
        table_name: Table to vacuum.
        schema_name: Schema name (default 'public').
        full: Whether to run VACUUM FULL (exclusive lock, rewrites table). Default False.
        analyze: Whether to also run ANALYZE to update statistics. Default True.

    Returns:
        A dict with the execution result and timing.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_privileged_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        from psycopg2 import sql

        validate_identifier(schema_name, kind="schema")
        validate_identifier(table_name, kind="table")

        # VACUUM options are internal literals built only from the fixed
        # words "FULL"/"ANALYZE" chosen by the bool flags — never caller input.
        options = []
        if full:
            options.append("FULL")
        if analyze:
            options.append("ANALYZE")

        option_str = " ".join(options)
        stmt = sql.SQL("VACUUM {opts} {sch}.{tbl}").format(
            opts=sql.SQL(option_str),
            sch=sql.Identifier(schema_name),
            tbl=sql.Identifier(table_name),
        )

        import time

        start = time.time()
        with conn.cursor() as cur:
            run_cursor(cur, stmt)
        elapsed = round(time.time() - start, 2)

        return {
            "db_identifier": db_identifier,
            "status": "completed",
            "table": f"{schema_name}.{table_name}",
            "sql_executed": stmt.as_string(conn),
            "duration_seconds": elapsed,
            "full": full,
            "analyze": analyze,
        }

    return {"error": f"execute_vacuum not implemented for engine: {engine}"}


@tool
def kill_session(db_identifier: str, pid: int, terminate: bool = False) -> dict:
    """Kill or cancel a blocking database session. Requires approval.

    By default uses pg_cancel_backend (graceful). Set terminate=True for pg_terminate_backend.

    Args:
        db_identifier: Target database identifier.
        pid: Process ID of the session to kill.
        terminate: If True, forcefully terminate. If False, cancel current query only.

    Returns:
        A dict with the result of the kill operation.
    """
    # Defensive coercion: pid is typed int, but force it so it can never
    # carry SQL text into the MySQL KILL statement below.
    pid = int(pid)
    entry = get_registry_entry(db_identifier)
    conn = get_privileged_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        # A whole static statement, chosen not built; pid is a bound parameter.
        query = postgres_kill_backend(terminate=terminate)
        with conn.cursor() as cur:
            run_cursor(cur, query, (pid,))
            result = cur.fetchone()[0]

        return {
            "db_identifier": db_identifier,
            "status": "completed",
            "pid": pid,
            "action": "terminate" if terminate else "cancel",
            "success": result,
        }

    elif "mysql" in engine:
        # MySQL cannot bind the connection id. The builder validates it to a
        # bounded positive integer, so the statement can only contain digits.
        stmt = mysql_kill(pid)
        with conn.cursor() as cur:
            run_cursor(cur, stmt)

        return {
            "db_identifier": db_identifier,
            "status": "completed",
            "pid": pid,
            "action": "kill",
            "success": True,
        }

    return {"error": f"kill_session not implemented for engine: {engine}"}


@tool
def trigger_backup(db_identifier: str, snapshot_identifier: str | None = None) -> dict:
    """Trigger an on-demand backup/snapshot. Requires approval.

    Args:
        db_identifier: Target database identifier.
        snapshot_identifier: Optional custom snapshot name. Auto-generated if not provided.

    Returns:
        A dict with the snapshot creation status.
    """
    entry = get_registry_entry(db_identifier)

    import boto3
    from datetime import datetime, timezone
    from src.config import settings

    rds = boto3.client("rds", region_name=settings.aws_region)

    if snapshot_identifier is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        snapshot_identifier = f"{db_identifier}-manual-{ts}"

    try:
        response = rds.create_db_snapshot(
            DBSnapshotIdentifier=snapshot_identifier,
            DBInstanceIdentifier=db_identifier,
        )
        snapshot = response["DBSnapshot"]
        return {
            "db_identifier": db_identifier,
            "status": "initiated",
            "snapshot_id": snapshot["DBSnapshotIdentifier"],
            "snapshot_status": snapshot["Status"],
        }
    except Exception as e:
        return {
            "db_identifier": db_identifier,
            "status": "failed",
            "error": str(e),
        }
