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

"""Index analysis tools — Tier 1 (read-only)."""

from strands import tool

from src.admin_ops.db.cursor_exec import run_cursor
from src.admin_ops.db.statements import explain_engine_family, explain_read_only
from src.tools._helpers import get_connection, get_registry_entry


@tool
def get_missing_indexes(db_identifier: str, min_impact: int = 100) -> dict:
    """Identify missing indexes with impact score based on sequential scans.

    Args:
        db_identifier: The database identifier from the fleet registry.
        min_impact: Minimum sequential scan count to consider (default 100).

    Returns:
        A dict with tables that would benefit from additional indexes.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    schemaname,
                    relname as table_name,
                    seq_scan,
                    seq_tup_read,
                    idx_scan,
                    CASE WHEN seq_scan + idx_scan > 0
                        THEN ROUND(100.0 * seq_scan / (seq_scan + idx_scan), 1)
                        ELSE 0
                    END as seq_scan_pct,
                    pg_size_pretty(pg_total_relation_size(schemaname || '.' || relname)) as table_size,
                    n_live_tup as estimated_rows
                FROM pg_stat_user_tables
                WHERE seq_scan > %s
                    AND n_live_tup > 1000
                ORDER BY seq_tup_read DESC
                LIMIT 20;
                """,
                (min_impact,),
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "missing_index_candidates": rows,
            "note": "Tables with high sequential scan ratios may benefit from indexes.",
        }

    elif "mysql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.table_schema,
                    t.table_name,
                    t.table_rows as estimated_rows,
                    s.rows_read,
                    s.rows_inserted + s.rows_updated + s.rows_deleted as write_ops
                FROM information_schema.tables t
                LEFT JOIN sys.schema_table_statistics s
                    ON t.table_name = s.table_name
                WHERE t.table_schema = DATABASE()
                    AND t.table_rows > 1000
                ORDER BY s.rows_read DESC
                LIMIT 20;
                """
            )
            rows = cur.fetchall()
        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "missing_index_candidates": rows,
        }

    return {"error": f"get_missing_indexes not implemented for engine: {engine}"}


@tool
def get_index_usage(db_identifier: str, schema_name: str = "public") -> dict:
    """Report index usage statistics to identify unused indexes.

    Args:
        db_identifier: The database identifier from the fleet registry.
        schema_name: Schema name (default 'public').

    Returns:
        A dict with index usage stats, highlighting unused indexes.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    schemaname,
                    relname as table_name,
                    indexrelname as index_name,
                    idx_scan as times_used,
                    idx_tup_read,
                    idx_tup_fetch,
                    pg_size_pretty(pg_relation_size(indexrelid)) as index_size,
                    pg_relation_size(indexrelid) as index_size_bytes
                FROM pg_stat_user_indexes
                WHERE schemaname = %s
                ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC;
                """,
                (schema_name,),
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]

        unused = [r for r in rows if r["times_used"] == 0]
        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "all_indexes": rows,
            "unused_indexes": unused,
            "unused_count": len(unused),
            "total_unused_size": sum(r["index_size_bytes"] for r in unused),
        }

    return {"error": f"get_index_usage not implemented for engine: {engine}"}


@tool
def get_execution_plan(db_identifier: str, query_text: str) -> dict:
    """Analyze the execution plan for a given SQL query.

    Args:
        db_identifier: The database identifier from the fleet registry.
        query_text: The SQL query to analyze (EXPLAIN ANALYZE will be used).

    Returns:
        A dict with the execution plan, estimated costs, and scan types.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    # `EXPLAIN <statement>` cannot bind the analysed statement as a parameter —
    # the statement is part of the command, not a value. That concatenation is
    # therefore done in exactly one place, `statements.explain_read_only`, which
    # validates the statement and applies the prefix in the same call so the
    # two cannot be separated. See that function for what is checked and why a
    # prefix check is not sufficient.
    family = explain_engine_family(engine)
    if family is None:
        return {"error": f"get_execution_plan not implemented for engine: {engine}"}

    explain_sql = explain_read_only(engine, query_text)
    with conn.cursor() as cur:
        run_cursor(cur, explain_sql)
        row = cur.fetchone()

    # PostgreSQL returns the JSON plan in the first column; MySQL returns the
    # row itself.
    plan = row[0] if family == "postgresql" else row
    return {
        "db_identifier": db_identifier,
        "engine": engine,
        "query": query_text[:200],
        "execution_plan": plan,
    }


@tool
def get_table_bloat(db_identifier: str, schema_name: str = "public") -> dict:
    """Report table bloat and dead tuple ratios for PostgreSQL databases.

    Args:
        db_identifier: The database identifier from the fleet registry.
        schema_name: Schema name (default 'public').

    Returns:
        A dict with bloat estimates per table.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    schemaname,
                    relname as table_name,
                    n_live_tup,
                    n_dead_tup,
                    CASE WHEN n_live_tup > 0
                        THEN ROUND(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 1)
                        ELSE 0
                    END as dead_tuple_pct,
                    last_vacuum::text,
                    last_autovacuum::text,
                    pg_size_pretty(pg_total_relation_size(schemaname || '.' || relname)) as table_size
                FROM pg_stat_user_tables
                WHERE schemaname = %s
                    AND n_dead_tup > 0
                ORDER BY n_dead_tup DESC
                LIMIT 20;
                """,
                (schema_name,),
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "table_bloat": rows,
            "high_bloat_tables": [r for r in rows if r["dead_tuple_pct"] > 20],
        }

    return {"error": f"get_table_bloat not implemented for engine: {engine}"}
