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

"""PostgreSQL DB Ops Agent — Real-time operations against Aurora PostgreSQL."""

import os
import json
import logging
import sys
import time
import boto3
import psycopg2
from psycopg2 import sql

# NOTE: BYPASS_TOOL_CONSENT is deliberately NOT set. Tier-3 (mutating) tool
# calls are gated by Tier3ApprovalHook below, which halts the agent loop until
# the operator supplies an explicit APPLY for that exact operation. Setting
# BYPASS_TOOL_CONSENT here would suppress the framework's own consent handling
# and must not be reintroduced.

from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

# Make repo root importable when launched from deploy/postgresql_agent/.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.admin_ops.registry.loader import registry  # noqa: E402
from src.admin_ops.db.identifiers import (  # noqa: E402
    validate_column_list,
    validate_identifier,
    validate_masking_type,
)
from src.admin_ops.db.cursor_exec import run_cursor  # noqa: E402
from src.admin_ops.db.sql_guard import assert_executable  # noqa: E402
from src.admin_ops.db.tls import postgres_ssl_kwargs  # noqa: E402
from src.hooks.tier3_approval import (  # noqa: E402
    Tier3ApprovalHook,
    pending_approvals,
)

# ─── Template registry startup hook (R1.3) ──────────────────────────────────────
_LOG = logging.getLogger(__name__)
_t = time.monotonic()
try:
    registry.load()
    _LOG.info(
        "template registry loaded in %.1f ms (%d templates, %d failures)",
        (time.monotonic() - _t) * 1000,
        len(registry.all()),
        len(registry.failures()),
    )
except Exception as _exc:  # pragma: no cover - never block agent startup
    _LOG.warning("template registry load failed: %s; falling back to in-source defaults", _exc)

app = BedrockAgentCoreApp()

# ─── Configuration ──────────────────────────────────────────────────────────────

SECRET_ARN = os.environ.get("PG_SECRET_ARN")
DEV_SECRET_ARN = os.environ.get("PG_DEV_SECRET_ARN")
REGION = os.environ.get("AWS_REGION", "us-east-1")

if not SECRET_ARN:
    raise RuntimeError(
        "PG_SECRET_ARN must be set. After deploying infra/cloudformation-123456789012.yaml, "
        "use the PostgresSecretArn output."
    )


def get_connection():
    """Get a live PostgreSQL connection using credentials from Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=REGION)
    secret = json.loads(client.get_secret_value(SecretId=SECRET_ARN)["SecretString"])
    conn = psycopg2.connect(
        host=secret["host"],
        port=int(secret["port"]),
        user=secret["username"],
        password=secret["password"],
        dbname=secret["dbname"],
        options="-c statement_timeout=30000",
        # Encryption in transit; see src/admin_ops/db/tls.py for the posture.
        **postgres_ssl_kwargs(secret["host"]),
    )
    conn.autocommit = True
    return conn


def get_dev_connection():
    """Get a connection to the dev/lower-env PostgreSQL for replication targets."""
    if not DEV_SECRET_ARN:
        raise RuntimeError(
            "PG_DEV_SECRET_ARN is not set. The clone-to-dev / replicate-to-dev tools "
            "require a separate Secrets Manager entry for the lower-env PostgreSQL."
        )
    client = boto3.client("secretsmanager", region_name=REGION)
    secret = json.loads(client.get_secret_value(SecretId=DEV_SECRET_ARN)["SecretString"])
    conn = psycopg2.connect(
        host=secret["host"],
        port=int(secret["port"]),
        user=secret["username"],
        password=secret["password"],
        dbname=secret["dbname"],
        options="-c statement_timeout=60000",
        # Encryption in transit; see src/admin_ops/db/tls.py for the posture.
        **postgres_ssl_kwargs(secret["host"]),
    )
    conn.autocommit = True
    return conn


SYSTEM_PROMPT = """You are an expert PostgreSQL Database Operations Agent connected to a LIVE Aurora PostgreSQL database.

All tool results are REAL data from the actual database — not simulated.

## Capabilities
- Tier 1 (Read-Only, +10 XP): Schema discovery, slow queries, active sessions, wait events, vacuum status, index analysis, replication status, masking policies
- Tier 2 (Advisory, +25 XP): Index recommendations with DDL
- Tier 3 (Actioned, +50 XP): Create/drop indexes, VACUUM, kill sessions, create replicas, clone to lower env, setup data masking, share snapshots — REQUIRES APPROVAL

## Rules
1. All data returned is LIVE from the connected database.
2. Never execute Tier 3 without explicit user approval.
3. Use CONCURRENTLY for production index operations.
4. For cloning to lower environments, always recommend data masking on sensitive columns.
5. For data sharing, always create a snapshot first then share — never share the live cluster.
6. Use emoji: 🟢 OK, 🟡 WARN, 🔴 CRITICAL
"""


# ─── Tier 1 Tools (Real Queries) ────────────────────────────────────────────────


@tool
def list_databases() -> dict:
    """List all databases on the connected PostgreSQL instance with their sizes."""
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, """
            SELECT datname, pg_database_size(datname) as size_bytes,
                   pg_size_pretty(pg_database_size(datname)) as size_pretty
            FROM pg_database WHERE datistemplate = false ORDER BY size_bytes DESC;
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return {"databases": rows, "count": len(rows)}


@tool
def list_tables(schema_name: str = "public") -> dict:
    """List all tables in the schema with row counts and sizes.

    Args:
        schema_name: Schema to list tables from (default: public).
    """
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, """
            SELECT schemaname, relname as table_name,
                   n_live_tup as estimated_rows,
                   pg_size_pretty(pg_total_relation_size(schemaname || '.' || relname)) as total_size,
                   pg_total_relation_size(schemaname || '.' || relname) as size_bytes
            FROM pg_stat_user_tables
            WHERE schemaname = %s
            ORDER BY pg_total_relation_size(schemaname || '.' || relname) DESC;
        """, (schema_name,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return {"schema": schema_name, "tables": rows, "count": len(rows)}


@tool
def get_slow_queries(top_n: int = 10) -> dict:
    """Get the top N slowest queries from pg_stat_statements (REAL DATA).

    Args:
        top_n: Number of slow queries to return.
    """
    _DEFAULT_BODY = """
            SELECT queryid, LEFT(query, 300) as query_text, calls,
                   round((total_exec_time / 1000)::numeric, 2) as total_time_sec,
                   round((mean_exec_time / 1000)::numeric, 3) as avg_time_sec,
                   rows
            FROM pg_stat_statements
            WHERE userid != 10
            ORDER BY mean_exec_time DESC
            LIMIT %(top_n)s;
        """
    params = {"top_n": top_n}
    try:
        spec = registry.must_get("pg_get_slow_queries")
        rendered = registry.render(spec.template_id, params)
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = params
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, body, params_for_db)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return {"slow_queries": rows, "count": len(rows)}


@tool
def get_active_sessions() -> dict:
    """Show all active (non-idle) sessions from pg_stat_activity (REAL DATA)."""
    _DEFAULT_BODY = """
            SELECT pid, usename, application_name, client_addr::text,
                   state, wait_event_type, wait_event,
                   LEFT(query, 200) as query_text,
                   EXTRACT(EPOCH FROM (now() - query_start))::int as duration_sec
            FROM pg_stat_activity
            WHERE state != 'idle' AND pid != pg_backend_pid()
            ORDER BY query_start ASC;
        """
    try:
        spec = registry.must_get("pg_get_active_sessions")
        rendered = registry.render(spec.template_id, {})
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = {}
    conn = get_connection()
    with conn.cursor() as cur:
        if params_for_db:
            run_cursor(cur, body, params_for_db)
        else:
            run_cursor(cur, body)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return {"active_sessions": rows, "total_active": len(rows)}


@tool
def get_wait_events() -> dict:
    """Report wait events grouped by type from pg_stat_activity (REAL DATA)."""
    _DEFAULT_BODY = """
            SELECT wait_event_type, wait_event, COUNT(*) as session_count,
                   SUM(EXTRACT(EPOCH FROM (now() - query_start)))::int as total_wait_sec
            FROM pg_stat_activity
            WHERE state != 'idle' AND wait_event IS NOT NULL AND pid != pg_backend_pid()
            GROUP BY wait_event_type, wait_event
            ORDER BY session_count DESC;
        """
    try:
        spec = registry.must_get("pg_get_wait_events")
        rendered = registry.render(spec.template_id, {})
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = {}
    conn = get_connection()
    with conn.cursor() as cur:
        if params_for_db:
            run_cursor(cur, body, params_for_db)
        else:
            run_cursor(cur, body)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return {"wait_events": rows}


@tool
def get_vacuum_status() -> dict:
    """Report vacuum status, dead tuples, and last vacuum times (REAL DATA)."""
    _DEFAULT_BODY = """
            SELECT schemaname, relname as table_name,
                   n_live_tup, n_dead_tup,
                   CASE WHEN n_live_tup > 0
                       THEN round(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 1)
                       ELSE 0 END as dead_pct,
                   last_vacuum::text, last_autovacuum::text,
                   vacuum_count, autovacuum_count
            FROM pg_stat_user_tables
            ORDER BY n_dead_tup DESC LIMIT 20;
        """
    try:
        spec = registry.must_get("pg_get_vacuum_status")
        rendered = registry.render(spec.template_id, {})
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = {}
    conn = get_connection()
    with conn.cursor() as cur:
        if params_for_db:
            run_cursor(cur, body, params_for_db)
        else:
            run_cursor(cur, body)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return {"vacuum_status": rows, "tables_needing_vacuum": [r for r in rows if r["dead_pct"] and r["dead_pct"] > 10]}


@tool
def get_index_usage(schema_name: str = "public") -> dict:
    """Report index usage stats — find unused indexes (REAL DATA).

    Args:
        schema_name: Schema to check.
    """
    _DEFAULT_BODY = """
            SELECT schemaname, relname as table_name, indexrelname as index_name,
                   idx_scan as times_used, idx_tup_read, idx_tup_fetch,
                   pg_size_pretty(pg_relation_size(indexrelid)) as index_size
            FROM pg_stat_user_indexes
            WHERE schemaname = %(schema_name)s
            ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC;
        """
    params = {"schema_name": schema_name}
    try:
        spec = registry.must_get("pg_get_index_usage")
        rendered = registry.render(spec.template_id, params)
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = params
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, body, params_for_db)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    unused = [r for r in rows if r["times_used"] == 0]
    return {"all_indexes": rows, "unused_indexes": unused, "unused_count": len(unused)}


@tool
def get_table_bloat(schema_name: str = "public") -> dict:
    """Report table bloat — dead tuple ratios (REAL DATA).

    Args:
        schema_name: Schema to check.
    """
    _DEFAULT_BODY = """
            SELECT schemaname, relname as table_name, n_live_tup, n_dead_tup,
                   CASE WHEN n_live_tup > 0
                       THEN round(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 1)
                       ELSE 0 END as dead_tuple_pct,
                   last_vacuum::text, last_autovacuum::text,
                   pg_size_pretty(pg_total_relation_size(schemaname || '.' || relname)) as table_size
            FROM pg_stat_user_tables
            WHERE schemaname = %(schema_name)s AND n_dead_tup > 0
            ORDER BY n_dead_tup DESC LIMIT 20;
        """
    params = {"schema_name": schema_name}
    try:
        spec = registry.must_get("pg_get_table_bloat")
        rendered = registry.render(spec.template_id, params)
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = params
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, body, params_for_db)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return {"table_bloat": rows}


@tool
def get_database_size() -> dict:
    """Get the total size of the current database and tablespace info (REAL DATA)."""
    _DEFAULT_BODY = """
            SELECT current_database() as db_name,
                   pg_size_pretty(pg_database_size(current_database())) as total_size,
                   pg_database_size(current_database()) as size_bytes;
        """
    try:
        spec = registry.must_get("pg_get_database_size")
        rendered = registry.render(spec.template_id, {})
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = {}
    conn = get_connection()
    with conn.cursor() as cur:
        if params_for_db:
            run_cursor(cur, body, params_for_db)
        else:
            run_cursor(cur, body)
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
    conn.close()
    return row


@tool
def get_connections_summary() -> dict:
    """Get connection count summary by state (REAL DATA)."""
    _DEFAULT_BODY = """
            SELECT state, COUNT(*) as count
            FROM pg_stat_activity
            GROUP BY state ORDER BY count DESC;
        """
    try:
        spec = registry.must_get("pg_get_connections_summary")
        rendered = registry.render(spec.template_id, {})
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = {}
    conn = get_connection()
    with conn.cursor() as cur:
        if params_for_db:
            run_cursor(cur, body, params_for_db)
        else:
            run_cursor(cur, body)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        run_cursor(cur, "SHOW max_connections;")
        max_conn = cur.fetchone()[0]
    conn.close()
    total = sum(r["count"] for r in rows)
    return {"connections_by_state": rows, "total_connections": total, "max_connections": int(max_conn)}


# ─── Tier 2 Tools ───────────────────────────────────────────────────────────────


@tool
def recommend_index(table_name: str, schema_name: str = "public") -> dict:
    """Analyze a table and recommend indexes based on sequential scan patterns (REAL DATA).

    Args:
        table_name: Table to analyze.
        schema_name: Schema name.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        # Get scan stats
        run_cursor(cur, """
            SELECT seq_scan, idx_scan, n_live_tup,
                   pg_size_pretty(pg_total_relation_size(schemaname || '.' || relname)) as size
            FROM pg_stat_user_tables
            WHERE schemaname = %s AND relname = %s;
        """, (schema_name, table_name))
        stats = cur.fetchone()

        # Get existing indexes
        run_cursor(cur, """
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname = %s AND tablename = %s;
        """, (schema_name, table_name))
        idx_cols = [d[0] for d in cur.description]
        indexes = [dict(zip(idx_cols, r)) for r in cur.fetchall()]

        # Get column stats
        run_cursor(cur, """
            SELECT attname, n_distinct, correlation
            FROM pg_stats WHERE schemaname = %s AND tablename = %s
            ORDER BY n_distinct DESC;
        """, (schema_name, table_name))
        col_cols = [d[0] for d in cur.description]
        col_stats = [dict(zip(col_cols, r)) for r in cur.fetchall()]
    conn.close()

    return {
        "table": f"{schema_name}.{table_name}",
        "scan_stats": {"seq_scan": stats[0], "idx_scan": stats[1], "rows": stats[2], "size": stats[3]} if stats else None,
        "existing_indexes": indexes,
        "column_statistics": col_stats,
    }


# ─── Tier 3 Tools ───────────────────────────────────────────────────────────────


@tool
def create_index(table_name: str, columns: str, index_name: str, schema_name: str = "public") -> dict:
    """Create an index CONCURRENTLY on the table. REQUIRES EXPLICIT APPROVAL.

    Args:
        table_name: Table to index.
        columns: Comma-separated column names.
        index_name: Name for the new index.
        schema_name: Schema name.
    """
    validate_identifier(schema_name, kind="schema")
    validate_identifier(table_name, kind="table")
    validate_identifier(index_name, kind="index")
    cols_list = validate_column_list(columns)
    ddl_stmt = sql.SQL(
        "CREATE INDEX CONCURRENTLY {idx} ON {sch}.{tbl} ({cols})"
    ).format(
        idx=sql.Identifier(index_name),
        sch=sql.Identifier(schema_name),
        tbl=sql.Identifier(table_name),
        cols=sql.SQL(", ").join(map(sql.Identifier, cols_list)),
    )
    conn = get_connection()
    import time
    start = time.time()
    with conn.cursor() as cur:
        run_cursor(cur, ddl_stmt)
        ddl = ddl_stmt.as_string(conn)
    elapsed = round(time.time() - start, 2)
    conn.close()
    return {"status": "success", "ddl": ddl, "duration_seconds": elapsed}


@tool
def kill_session(pid: int) -> dict:
    """Terminate a PostgreSQL backend process. REQUIRES EXPLICIT APPROVAL.

    Args:
        pid: Process ID to terminate.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, "SELECT pg_terminate_backend(%s);", (pid,))
        result = cur.fetchone()[0]
    conn.close()
    return {"pid": pid, "terminated": result}


@tool
def execute_vacuum(table_name: str, schema_name: str = "public", analyze: bool = True) -> dict:
    """Execute VACUUM on a table. REQUIRES EXPLICIT APPROVAL.

    Args:
        table_name: Table to vacuum.
        schema_name: Schema name.
        analyze: Also run ANALYZE (default True).
    """
    validate_identifier(schema_name, kind="schema")
    validate_identifier(table_name, kind="table")
    # Option keyword comes from a fixed allowlist, never caller input.
    option_sql = sql.SQL("ANALYZE") if analyze else sql.SQL("")
    vacuum_stmt = sql.SQL("VACUUM {opt} {sch}.{tbl}").format(
        opt=option_sql,
        sch=sql.Identifier(schema_name),
        tbl=sql.Identifier(table_name),
    )
    conn = get_connection()
    import time
    start = time.time()
    with conn.cursor() as cur:
        run_cursor(cur, vacuum_stmt)
        rendered_sql = vacuum_stmt.as_string(conn)
    elapsed = round(time.time() - start, 2)
    conn.close()
    return {"status": "success", "sql": rendered_sql, "duration_seconds": elapsed}


# ─── Tier 3 — Replicas & Cloning ────────────────────────────────────────────────


@tool
def create_read_replica(source_db_identifier: str, replica_identifier: str, instance_class: str = "db.t3.medium") -> dict:
    """Create a read replica of an Aurora/RDS PostgreSQL instance. REQUIRES APPROVAL.

    Args:
        source_db_identifier: Source DB cluster or instance identifier.
        replica_identifier: Identifier for the new replica.
        instance_class: Instance class for the replica (default db.t3.medium).
    """
    import boto3
    rds = boto3.client("rds", region_name=REGION)
    try:
        # Encryption at rest: this adds an instance to an existing Aurora
        # cluster (note DBClusterIdentifier), and for Aurora encryption is a
        # property of the *cluster*, not of the instance. The instance inherits
        # it, and StorageEncrypted is not a valid parameter for this call shape
        # — passing it here would be rejected. The clusters created by
        # infra/cloudformation.yaml set `StorageEncrypted: true`
        # (AuroraPostgresCluster, LowerEnvPostgresCluster), so replicas of them
        # are encrypted.
        #
        # If you adapt this call to create a *standalone, non-Aurora* RDS
        # instance — dropping DBClusterIdentifier and using Engine="postgres" —
        # you must pass StorageEncrypted=True explicitly. It defaults to false
        # there, so an otherwise-working copy of this code would create an
        # unencrypted database.
        response = rds.create_db_instance(
            DBInstanceIdentifier=replica_identifier,
            DBClusterIdentifier=source_db_identifier,
            DBInstanceClass=instance_class,
            Engine="aurora-postgresql",
            PubliclyAccessible=False,
        )
        instance = response["DBInstance"]
        return {
            "status": "creating",
            "replica_id": instance["DBInstanceIdentifier"],
            "instance_class": instance["DBInstanceClass"],
            "endpoint": instance.get("Endpoint", {}).get("Address", "pending"),
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def get_replication_status(cluster_identifier: str) -> dict:
    """Check replication lag and status for all replicas in a cluster.

    Args:
        cluster_identifier: The Aurora cluster identifier.
    """
    import boto3
    rds = boto3.client("rds", region_name=REGION)
    try:
        response = rds.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
        cluster = response["DBClusters"][0]
        members = cluster.get("DBClusterMembers", [])
        replicas = []
        for m in members:
            replicas.append({
                "instance_id": m["DBInstanceIdentifier"],
                "is_writer": m["IsClusterWriter"],
                "promotion_tier": m.get("PromotionTier"),
            })
        return {
            "cluster": cluster_identifier,
            "status": cluster["Status"],
            "members": replicas,
            "reader_endpoint": cluster.get("ReaderEndpoint"),
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def clone_to_lower_env(source_cluster: str, target_cluster_name: str, target_instance_class: str = "db.t3.micro") -> dict:
    """Clone a production Aurora cluster to a lower environment (dev/staging) using restore-from-snapshot. REQUIRES APPROVAL.

    Creates a snapshot of the source, then restores it as a new cluster.

    Args:
        source_cluster: Source Aurora cluster identifier to clone from.
        target_cluster_name: Name for the new lower-env cluster.
        target_instance_class: Instance class for the clone (default db.t3.micro for cost savings).
    """
    import boto3
    from datetime import datetime, timezone
    rds = boto3.client("rds", region_name=REGION)

    snapshot_id = f"{source_cluster}-clone-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    try:
        # Step 1: Create snapshot
        rds.create_db_cluster_snapshot(
            DBClusterIdentifier=source_cluster,
            DBClusterSnapshotIdentifier=snapshot_id,
        )

        return {
            "status": "snapshot_initiated",
            "snapshot_id": snapshot_id,
            "target_cluster": target_cluster_name,
            "target_instance_class": target_instance_class,
            "next_step": f"Once snapshot is available, restore with: aws rds restore-db-cluster-from-snapshot --db-cluster-identifier {target_cluster_name} --snapshot-identifier {snapshot_id} --engine aurora-postgresql",
            "note": "Snapshot creation takes 5-15 minutes. The clone will be an exact copy of production data.",
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ─── Tier 3 — Data Masking ──────────────────────────────────────────────────────


# Returned in every setup_data_masking response so the operator who ran the tool
# sees it, not only someone who reads this file.
MASKING_COMPLIANCE_WARNING = (
    "WARNING: this masking is a development convenience and does NOT satisfy "
    "HIPAA, PCI DSS, or GDPR requirements. It is not anonymisation. Under the "
    "AWS shared responsibility model, meeting those obligations for regulated "
    "data remains yours, and requires proper de-identification, encryption, and "
    "access controls. Three specific limits: 'partial' preserves the first and "
    "last characters, so in a small population it can still identify an "
    "individual; 'hash' is deterministic and unsalted, so equal inputs give "
    "equal hashes and values stay linkable across tables and open to a "
    "dictionary attack over a small domain; and the base table is untouched, so "
    "any role that can read it directly still sees cleartext and must be "
    "revoked separately."
)

@tool
def setup_data_masking(table_name: str, columns_to_mask: str, masking_type: str = "partial", schema_name: str = "public") -> dict:
    """Set up dynamic data masking on specified columns using PostgreSQL security policies. REQUIRES APPROVAL.

    Creates a masking view and role-based access so non-privileged users see masked data.

    WARNING: this is a development convenience, NOT a compliance control. It
    does not satisfy HIPAA, PCI DSS, or GDPR, and it is not anonymisation.
    'partial' leaves the first and last characters in place, which can still
    identify someone in a small population; 'hash' is deterministic and
    unsalted, so values stay linkable and open to a dictionary attack over a
    small domain; and the base table is unchanged, so any role that can read
    it directly still sees cleartext and must be revoked separately. The full
    text is returned in the response as `compliance_warning`.

    Args:
        table_name: Table to apply masking on.
        columns_to_mask: Comma-separated column names to mask (e.g., "email,phone,ssn").
        masking_type: Type of masking - 'partial' (show first/last chars), 'full' (replace entirely), 'hash' (SHA256).
        schema_name: Schema name.
    """
    validate_identifier(schema_name, kind="schema")
    validate_identifier(table_name, kind="table")
    validate_masking_type(masking_type)
    columns = validate_column_list(columns_to_mask)
    conn = get_connection()
    masked_view = validate_identifier(table_name + "_masked", kind="view")
    results = []

    with conn.cursor() as cur:
        # Build masked column expressions
        masked_cols = []
        for col in columns:
            if masking_type == "partial":
                expr = f"LEFT({col}, 2) || '****' || RIGHT({col}, 2) AS {col}"
            elif masking_type == "full":
                expr = f"'*****' AS {col}"
            elif masking_type == "hash":
                expr = f"encode(sha256({col}::bytea), 'hex') AS {col}"
            else:
                expr = f"'*****' AS {col}"
            masked_cols.append(expr)

        # Get all columns and replace masked ones
        run_cursor(cur, """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position;
        """, (schema_name, table_name))
        all_cols = [r[0] for r in cur.fetchall()]

        # Compose the SELECT list: masked columns use fixed literal SQL for the
        # function calls with the column bound as a safely-quoted identifier;
        # unmasked columns are emitted as plain identifiers.
        select_exprs = []
        for col in all_cols:
            if col in columns:
                if masking_type == "partial":
                    select_exprs.append(
                        sql.SQL(
                            "LEFT({c}::text, 2) || '****' || RIGHT({c}::text, 2) AS {c}"
                        ).format(c=sql.Identifier(col))
                    )
                elif masking_type == "full":
                    select_exprs.append(
                        sql.SQL("'*****'::text AS {c}").format(c=sql.Identifier(col))
                    )
                else:
                    select_exprs.append(
                        sql.SQL(
                            "encode(sha256({c}::text::bytea), 'hex') AS {c}"
                        ).format(c=sql.Identifier(col))
                    )
            else:
                select_exprs.append(sql.Identifier(col))

        # Create masked view
        view_stmt = sql.SQL(
            "CREATE OR REPLACE VIEW {sch}.{view} AS SELECT {cols} FROM {sch}.{tbl}"
        ).format(
            sch=sql.Identifier(schema_name),
            view=sql.Identifier(masked_view),
            cols=sql.SQL(", ").join(select_exprs),
            tbl=sql.Identifier(table_name),
        )
        run_cursor(cur, view_stmt)
        results.append(f"Created masked view: {schema_name}.{masked_view}")

        # Create masking role
        try:
            run_cursor(cur, "CREATE ROLE masked_reader;")
            results.append("Created role: masked_reader")
        except Exception:
            results.append("Role masked_reader already exists")

        # Grant access to masked view only. The role name is a fixed literal,
        # composed as an identifier for safe quoting.
        grant_stmt = sql.SQL("GRANT SELECT ON {sch}.{view} TO {role}").format(
            sch=sql.Identifier(schema_name),
            view=sql.Identifier(masked_view),
            role=sql.Identifier("masked_reader"),
        )
        run_cursor(cur, grant_stmt)
        results.append(f"Granted SELECT on {masked_view} to masked_reader")

    conn.close()
    return {
        "status": "success",
        "table": f"{schema_name}.{table_name}",
        "masked_view": f"{schema_name}.{masked_view}",
        "columns_masked": columns,
        "masking_type": masking_type,
        "actions": results,
        "usage": f"Users with 'masked_reader' role will see masked data via: SELECT * FROM {schema_name}.{masked_view}",  # nosec B608  # human-readable message, not executed
        "compliance_warning": MASKING_COMPLIANCE_WARNING,
    }


@tool
def get_masking_policies() -> dict:
    """List all data masking views and policies currently configured in the database."""
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, """
            SELECT schemaname, viewname, definition
            FROM pg_views
            WHERE viewname LIKE '%_masked'
            ORDER BY schemaname, viewname;
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return {"masking_views": rows, "count": len(rows)}


# ─── Tier 2/3 — Data Sharing ────────────────────────────────────────────────────


@tool
def replicate_table_with_masking(table_name: str, columns_to_mask: str, masking_type: str = "partial", schema_name: str = "public") -> dict:
    """Replicate a table from production to the dev environment with data masking applied. REQUIRES APPROVAL.

    Reads data from prod, applies masking to specified columns, and inserts into the dev database.

    Args:
        table_name: Table to replicate.
        columns_to_mask: Comma-separated column names to mask during replication.
        masking_type: 'partial', 'full', or 'hash'.
        schema_name: Schema name.
    """
    import time
    validate_identifier(schema_name, kind="schema")
    validate_identifier(table_name, kind="table")
    columns = validate_column_list(columns_to_mask)

    # Connect to both environments
    prod_conn = get_connection()
    dev_conn = get_dev_connection()

    try:
        with prod_conn.cursor() as cur:
            # Get all columns
            run_cursor(cur, """
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position;
            """, (schema_name, table_name))
            all_columns = [(r[0], r[1]) for r in cur.fetchall()]

            if not all_columns:
                return {"status": "failed", "error": f"Table {schema_name}.{table_name} not found or has no columns"}

            col_names = [c[0] for c in all_columns]

            # Read from prod
            run_cursor(cur, 
                sql.SQL("SELECT * FROM {sch}.{tbl}").format(
                    sch=sql.Identifier(schema_name),
                    tbl=sql.Identifier(table_name),
                )
            )
            rows = cur.fetchall()

        # Create table in dev if not exists
        with dev_conn.cursor() as dev_cur:
            # Get CREATE TABLE DDL from prod. The generated DDL text is built by
            # string_agg on the server; the qualified table name is injected as a
            # bound string literal (safe: schema/table are validated identifiers).
            with prod_conn.cursor() as cur:
                run_cursor(cur, 
                    sql.SQL(
                        "SELECT 'CREATE TABLE IF NOT EXISTS ' || {qualified} || ' (' || "
                        "string_agg(column_name || ' ' || data_type || "
                        "CASE WHEN character_maximum_length IS NOT NULL "
                        "THEN '(' || character_maximum_length || ')' ELSE '' END, "
                        "', ' ORDER BY ordinal_position) || ')' "
                        "FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = %s"
                    ).format(qualified=sql.Literal(schema_name + "." + table_name)),
                    (schema_name, table_name),
                )
                create_ddl = cur.fetchone()[0]

            if create_ddl:
                run_cursor(dev_cur, create_ddl)

            # Truncate dev table
            run_cursor(dev_cur, 
                sql.SQL("TRUNCATE TABLE {sch}.{tbl}").format(
                    sch=sql.Identifier(schema_name),
                    tbl=sql.Identifier(table_name),
                )
            )

            # Apply masking and insert
            masked_count = 0
            for row in rows:
                masked_row = list(row)
                for i, col_name in enumerate(col_names):
                    if col_name in columns and masked_row[i] is not None:
                        val = str(masked_row[i])
                        if masking_type == "partial":
                            masked_row[i] = val[:2] + "****" + val[-2:] if len(val) > 4 else "****"
                        elif masking_type == "full":
                            masked_row[i] = "*****"
                        elif masking_type == "hash":
                            import hashlib
                            masked_row[i] = hashlib.sha256(val.encode()).hexdigest()[:16]

                insert_stmt = sql.SQL("INSERT INTO {sch}.{tbl} VALUES ({vals})").format(
                    sch=sql.Identifier(schema_name),
                    tbl=sql.Identifier(table_name),
                    vals=sql.SQL(", ").join(sql.Placeholder() for _ in masked_row),
                )
                run_cursor(dev_cur, insert_stmt, masked_row)
                masked_count += 1

        prod_conn.close()
        dev_conn.close()

        return {
            "status": "success",
            "table": f"{schema_name}.{table_name}",
            "rows_replicated": masked_count,
            "columns_masked": columns,
            "masking_type": masking_type,
            "source": "production (Aurora PG)",
            "target": "development (Dev Aurora PG)",
        }
    except Exception as e:
        prod_conn.close()
        dev_conn.close()
        return {"status": "failed", "error": str(e)}


@tool
def list_dev_databases() -> dict:
    """List all databases on the dev/lower-environment PostgreSQL instance."""
    dev_conn = get_dev_connection()
    with dev_conn.cursor() as cur:
        run_cursor(cur, """
            SELECT datname, pg_database_size(datname) as size_bytes,
                   pg_size_pretty(pg_database_size(datname)) as size_pretty
            FROM pg_database WHERE datistemplate = false ORDER BY size_bytes DESC;
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    dev_conn.close()
    return {"environment": "development", "databases": rows, "count": len(rows)}


@tool
def share_data_snapshot(source_cluster: str, target_account_id: str) -> dict:
    """Share a DB cluster snapshot with another AWS account for cross-account data sharing. REQUIRES APPROVAL.

    Args:
        source_cluster: Source Aurora cluster identifier.
        target_account_id: AWS account ID to share the snapshot with.
    """
    import boto3
    from datetime import datetime, timezone
    rds = boto3.client("rds", region_name=REGION)

    snapshot_id = f"{source_cluster}-share-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    try:
        # Create snapshot
        rds.create_db_cluster_snapshot(
            DBClusterIdentifier=source_cluster,
            DBClusterSnapshotIdentifier=snapshot_id,
        )

        # Note: sharing requires snapshot to be available first
        return {
            "status": "snapshot_initiated",
            "snapshot_id": snapshot_id,
            "target_account": target_account_id,
            "next_step": f"Once snapshot is available, share with: aws rds modify-db-cluster-snapshot-attribute --db-cluster-snapshot-identifier {snapshot_id} --attribute-name restore --values-to-add {target_account_id}",
            "note": "The target account can then restore from this shared snapshot.",
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ─── Tier 1 — Lock Management & Blocking ─────────────────────────────────────────


@tool
def detect_blocking_chains() -> dict:
    """Detect blocking chains — shows who is blocking whom and for how long."""
    _DEFAULT_BODY = """
            SELECT
                blocked.pid AS blocked_pid,
                blocked.usename AS blocked_user,
                LEFT(blocked.query, 150) AS blocked_query,
                EXTRACT(EPOCH FROM (now() - blocked.query_start))::int AS blocked_duration_sec,
                blocking.pid AS blocking_pid,
                blocking.usename AS blocking_user,
                LEFT(blocking.query, 150) AS blocking_query,
                EXTRACT(EPOCH FROM (now() - blocking.query_start))::int AS blocking_duration_sec
            FROM pg_stat_activity blocked
            JOIN pg_locks bl ON bl.pid = blocked.pid AND NOT bl.granted
            JOIN pg_locks gl ON gl.locktype = bl.locktype AND gl.database IS NOT DISTINCT FROM bl.database
                AND gl.relation IS NOT DISTINCT FROM bl.relation AND gl.page IS NOT DISTINCT FROM bl.page
                AND gl.tuple IS NOT DISTINCT FROM bl.tuple AND gl.virtualxid IS NOT DISTINCT FROM bl.virtualxid
                AND gl.transactionid IS NOT DISTINCT FROM bl.transactionid AND gl.classid IS NOT DISTINCT FROM bl.classid
                AND gl.objid IS NOT DISTINCT FROM bl.objid AND gl.objsubid IS NOT DISTINCT FROM bl.objsubid
                AND gl.pid != bl.pid AND gl.granted
            JOIN pg_stat_activity blocking ON blocking.pid = gl.pid
            ORDER BY blocked_duration_sec DESC;
        """
    try:
        spec = registry.must_get("pg_detect_blocking_chains")
        rendered = registry.render(spec.template_id, {})
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = {}
    conn = get_connection()
    with conn.cursor() as cur:
        if params_for_db:
            run_cursor(cur, body, params_for_db)
        else:
            run_cursor(cur, body)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return {"blocking_chains": rows, "count": len(rows), "has_blockers": len(rows) > 0}


@tool
def get_cloudwatch_metrics(instance_identifier: str, period_minutes: int = 60) -> dict:
    """Get CloudWatch metrics for an RDS/Aurora instance: CPU, memory, IOPS, disk, connections.

    Args:
        instance_identifier: The DB instance identifier (e.g., dbops-demo-aurora-pg-1).
        period_minutes: Lookback period in minutes.
    """
    import boto3
    from datetime import datetime, timedelta, timezone
    cw = boto3.client("cloudwatch", region_name=REGION)
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=period_minutes)

    metrics_to_get = ["CPUUtilization", "FreeableMemory", "ReadIOPS", "WriteIOPS", "FreeStorageSpace", "DatabaseConnections", "SwapUsage"]
    results = {}
    for metric in metrics_to_get:
        try:
            resp = cw.get_metric_statistics(
                Namespace="AWS/RDS", MetricName=metric,
                Dimensions=[{"Name": "DBInstanceIdentifier", "Value": instance_identifier}],
                StartTime=start, EndTime=end, Period=300, Statistics=["Average", "Maximum"],
            )
            dps = sorted(resp["Datapoints"], key=lambda x: x["Timestamp"])
            if dps:
                results[metric] = {"average": round(dps[-1].get("Average", 0), 2), "maximum": round(dps[-1].get("Maximum", 0), 2)}
            else:
                results[metric] = {"note": "No data"}
        except Exception as e:
            results[metric] = {"error": str(e)}
    return {"instance": instance_identifier, "period_minutes": period_minutes, "metrics": results}


@tool
def check_txid_wraparound() -> dict:
    """Check transaction ID wraparound proximity — critical PostgreSQL safety check.

    Returns databases approaching the 2-billion transaction limit that triggers forced VACUUM.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, """
            SELECT datname, age(datfrozenxid) as xid_age,
                   round(100 * age(datfrozenxid) / 2147483647.0, 2) as pct_towards_wraparound,
                   2147483647 - age(datfrozenxid) as remaining_xids
            FROM pg_database
            WHERE datallowconn ORDER BY age(datfrozenxid) DESC;
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    critical = [r for r in rows if r["pct_towards_wraparound"] > 50]
    return {"databases": rows, "critical": critical, "has_risk": len(critical) > 0}


# ─── Tier 3 — Security & Access Management ──────────────────────────────────────


@tool
def create_db_user(username: str, password: str, readonly: bool = True) -> dict:
    """Create a new database user/role. REQUIRES APPROVAL.

    Args:
        username: New username to create.
        password: Password for the user.
        readonly: If True, grants SELECT only. If False, grants full DML.
    """
    validate_identifier(username, kind="role")
    role = sql.Identifier(username)
    conn = get_connection()
    with conn.cursor() as cur:
        # Password stays a bound parameter; only the role identifier is composed.
        run_cursor(cur, 
            sql.SQL("CREATE ROLE {role} WITH LOGIN PASSWORD %s").format(role=role),
            (password,),
        )
        if readonly:
            run_cursor(cur, sql.SQL("GRANT CONNECT ON DATABASE appdb TO {role}").format(role=role))
            run_cursor(cur, sql.SQL("GRANT USAGE ON SCHEMA public TO {role}").format(role=role))
            run_cursor(cur, 
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}").format(role=role)
            )
        else:
            run_cursor(cur, 
                sql.SQL(
                    "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {role}"
                ).format(role=role)
            )
    conn.close()
    return {"status": "success", "username": username, "readonly": readonly}


@tool
def drop_db_user(username: str) -> dict:
    """Drop a database user/role. REQUIRES APPROVAL.

    Args:
        username: Username to drop.
    """
    validate_identifier(username, kind="role")
    role = sql.Identifier(username)
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, 
            sql.SQL(
                "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {role}"
            ).format(role=role)
        )
        run_cursor(cur, sql.SQL("DROP ROLE IF EXISTS {role}").format(role=role))
    conn.close()
    return {"status": "success", "dropped": username}


@tool
def trigger_backup(cluster_identifier: str) -> dict:
    """Trigger an on-demand snapshot/backup of the Aurora cluster. REQUIRES APPROVAL.

    Args:
        cluster_identifier: Aurora cluster identifier to backup.
    """
    import boto3
    from datetime import datetime, timezone
    rds = boto3.client("rds", region_name=REGION)
    snapshot_id = f"{cluster_identifier}-manual-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    try:
        rds.create_db_cluster_snapshot(DBClusterIdentifier=cluster_identifier, DBClusterSnapshotIdentifier=snapshot_id)
        return {"status": "initiated", "snapshot_id": snapshot_id, "cluster": cluster_identifier}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ─── Tier 3 — DDL & Data Operations ─────────────────────────────────────────────


@tool
def reindex_concurrently(index_name: str, schema_name: str = "public") -> dict:
    """Rebuild a bloated index without locking the table. REQUIRES APPROVAL.

    Args:
        index_name: Index to rebuild.
        schema_name: Schema name.
    """
    validate_identifier(schema_name, kind="schema")
    validate_identifier(index_name, kind="index")
    conn = get_connection()
    import time
    start = time.time()
    with conn.cursor() as cur:
        run_cursor(cur, 
            sql.SQL("REINDEX INDEX CONCURRENTLY {sch}.{idx}").format(
                sch=sql.Identifier(schema_name),
                idx=sql.Identifier(index_name),
            )
        )
    elapsed = round(time.time() - start, 2)
    conn.close()
    return {"status": "success", "index": index_name, "duration_seconds": elapsed}


@tool
def execute_sql(sql: str) -> dict:
    """Execute an arbitrary SQL statement against the production database. REQUIRES APPROVAL.

    Use for CREATE TABLE, ALTER TABLE, INSERT, UPDATE, DELETE, DROP TABLE, etc.
    Returns affected rows for DML, or confirmation for DDL.

    Args:
        sql: The SQL statement to execute.
    """
    # Defense in depth beneath the Tier-3 approval gate: refuse stacked
    # statements (which could smuggle an unapproved second statement past a
    # fingerprinted approval) and refuse constructs that reach outside the
    # database entirely, such as COPY ... FROM PROGRAM.
    assert_executable(sql)
    conn = get_connection()
    import time
    start = time.time()
    with conn.cursor() as cur:
        run_cursor(cur, sql)  # nosec B608
        elapsed = round(time.time() - start, 2)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()
            return {"status": "success", "rows": rows, "count": len(rows), "duration_seconds": elapsed}
        else:
            rowcount = cur.rowcount
            conn.close()
            return {"status": "success", "rows_affected": rowcount, "sql": sql[:200], "duration_seconds": elapsed}


@tool
def execute_sql_on_dev(sql: str) -> dict:
    """Execute an arbitrary SQL statement against the DEV database. REQUIRES APPROVAL.

    Use for CREATE TABLE, ALTER TABLE, INSERT, UPDATE, DELETE, DROP TABLE on the lower environment.

    Args:
        sql: The SQL statement to execute.
    """
    # Same guard as the production path: the dev database is still reachable
    # infrastructure, so host-escape constructs are refused here too.
    assert_executable(sql)
    dev_conn = get_dev_connection()
    import time
    start = time.time()
    with dev_conn.cursor() as cur:
        run_cursor(cur, sql)
        elapsed = round(time.time() - start, 2)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            dev_conn.close()
            return {"status": "success", "environment": "development", "rows": rows, "count": len(rows), "duration_seconds": elapsed}
        else:
            rowcount = cur.rowcount
            dev_conn.close()
            return {"status": "success", "environment": "development", "rows_affected": rowcount, "sql": sql[:200], "duration_seconds": elapsed}


@tool
def load_data_from_s3(table_name: str, s3_uri: str, schema_name: str = "public") -> dict:
    """Load data from an S3 file (CSV/JSON) into a PostgreSQL table. REQUIRES APPROVAL.

    Downloads the file from S3, parses it, and inserts rows into the table.
    Supports CSV (first row = headers) and JSON (array of objects).

    Args:
        table_name: Target table to load data into.
        s3_uri: S3 URI of the file (e.g., s3://bucket/path/file.csv).
        schema_name: Schema name.
    """
    import boto3
    import csv
    import io

    validate_identifier(schema_name, kind="schema")
    validate_identifier(table_name, kind="table")

    # Parse S3 URI
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    key = parts[1]

    # Encryption is already covered on both legs and needs no extra parameters:
    # in transit, boto3 talks to S3 over HTTPS by default; at rest, every object
    # is encrypted with SSE-S3 (AES-256) unless the bucket specifies a different
    # key, which S3 has applied to new objects by default since January 2023.
    # GetObject decrypts transparently for a caller with permission on the
    # object and, for SSE-KMS buckets, on the key. To *require* a particular
    # scheme rather than accept the default, enforce it on the bucket with a
    # policy condition on s3:x-amz-server-side-encryption.
    s3 = boto3.client("s3", region_name=REGION)
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    conn = get_connection()
    rows_inserted = 0

    if key.endswith(".json"):
        import json as json_mod
        items = json_mod.loads(content)
        if not isinstance(items, list):
            items = items.get("Items", items.get("items", [items]))
        if items:
            headers = validate_column_list(list(items[0].keys()))
            insert_stmt = sql.SQL(
                "INSERT INTO {sch}.{tbl} ({cols}) VALUES ({vals})"
            ).format(
                sch=sql.Identifier(schema_name),
                tbl=sql.Identifier(table_name),
                cols=sql.SQL(", ").join(map(sql.Identifier, headers)),
                vals=sql.SQL(", ").join(sql.Placeholder() for _ in headers),
            )
            with conn.cursor() as cur:
                for item in items:
                    values = [str(item.get(h, "")) for h in headers]
                    run_cursor(cur, insert_stmt, values)
                    rows_inserted += 1
    else:
        reader = csv.reader(io.StringIO(content))
        headers = validate_column_list(next(reader))
        insert_stmt = sql.SQL(
            "INSERT INTO {sch}.{tbl} ({cols}) VALUES ({vals})"
        ).format(
            sch=sql.Identifier(schema_name),
            tbl=sql.Identifier(table_name),
            cols=sql.SQL(", ").join(map(sql.Identifier, headers)),
            vals=sql.SQL(", ").join(sql.Placeholder() for _ in headers),
        )
        with conn.cursor() as cur:
            for row in reader:
                if row:
                    run_cursor(cur, insert_stmt, row)
                    rows_inserted += 1

    conn.close()
    return {"status": "success", "table": f"{schema_name}.{table_name}", "s3_uri": s3_uri, "rows_inserted": rows_inserted}


@tool
def load_data_from_csv(table_name: str, csv_data: str, schema_name: str = "public") -> dict:
    """Load CSV data into a table. REQUIRES APPROVAL.

    Parses the CSV string and inserts rows into the specified table.
    First row must be column headers.

    Args:
        table_name: Target table to load data into.
        csv_data: CSV content as a string (first row = headers).
        schema_name: Schema name.
    """
    import csv
    import io

    validate_identifier(schema_name, kind="schema")
    validate_identifier(table_name, kind="table")

    conn = get_connection()
    reader = csv.reader(io.StringIO(csv_data))
    headers = validate_column_list(next(reader))
    rows_inserted = 0

    with conn.cursor() as cur:
        insert_stmt = sql.SQL(
            "INSERT INTO {sch}.{tbl} ({cols}) VALUES ({vals})"
        ).format(
            sch=sql.Identifier(schema_name),
            tbl=sql.Identifier(table_name),
            cols=sql.SQL(", ").join(map(sql.Identifier, headers)),
            vals=sql.SQL(", ").join(sql.Placeholder() for _ in headers),
        )

        for row in reader:
            run_cursor(cur, insert_stmt, row)
            rows_inserted += 1

    conn.close()
    return {"status": "success", "table": f"{schema_name}.{table_name}", "rows_inserted": rows_inserted, "columns": headers}


# ─── Tier 3 — Auto Scaling & Instance Scaling ────────────────────────────────────


@tool
def configure_aurora_autoscaling(cluster_identifier: str, min_replicas: int = 1, max_replicas: int = 4, target_cpu: int = 70) -> dict:
    """Configure Aurora Auto Scaling policy for read replicas. REQUIRES APPROVAL.

    Sets up a target-tracking scaling policy that adds/removes read replicas
    based on average CPU utilization.

    Args:
        cluster_identifier: Aurora cluster identifier.
        min_replicas: Minimum number of read replicas (default 1).
        max_replicas: Maximum number of read replicas (default 4).
        target_cpu: Target CPU utilization percentage to maintain (default 70).
    """
    import boto3
    app_autoscaling = boto3.client("application-autoscaling", region_name=REGION)
    resource_id = f"cluster:{cluster_identifier}"

    try:
        # Register scalable target
        app_autoscaling.register_scalable_target(
            ServiceNamespace="rds",
            ResourceId=resource_id,
            ScalableDimension="rds:cluster:ReadReplicaCount",
            MinCapacity=min_replicas,
            MaxCapacity=max_replicas,
        )

        # Create target-tracking scaling policy
        policy_name = f"{cluster_identifier}-cpu-scaling"
        app_autoscaling.put_scaling_policy(
            PolicyName=policy_name,
            ServiceNamespace="rds",
            ResourceId=resource_id,
            ScalableDimension="rds:cluster:ReadReplicaCount",
            PolicyType="TargetTrackingScaling",
            TargetTrackingScalingPolicyConfiguration={
                "TargetValue": float(target_cpu),
                "PredefinedMetricSpecification": {
                    "PredefinedMetricType": "RDSReaderAverageCPUUtilization",
                },
                "ScaleInCooldown": 300,
                "ScaleOutCooldown": 300,
            },
        )

        return {
            "status": "success",
            "cluster": cluster_identifier,
            "policy_name": policy_name,
            "min_replicas": min_replicas,
            "max_replicas": max_replicas,
            "target_cpu_pct": target_cpu,
            "scale_in_cooldown": 300,
            "scale_out_cooldown": 300,
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def get_autoscaling_status(cluster_identifier: str) -> dict:
    """Check current Aurora Auto Scaling configuration and activity.

    Args:
        cluster_identifier: Aurora cluster identifier.
    """
    import boto3
    app_autoscaling = boto3.client("application-autoscaling", region_name=REGION)
    resource_id = f"cluster:{cluster_identifier}"

    try:
        # Get scalable targets
        targets = app_autoscaling.describe_scalable_targets(
            ServiceNamespace="rds",
            ResourceIds=[resource_id],
            ScalableDimension="rds:cluster:ReadReplicaCount",
        )

        # Get scaling policies
        policies = app_autoscaling.describe_scaling_policies(
            ServiceNamespace="rds",
            ResourceId=resource_id,
            ScalableDimension="rds:cluster:ReadReplicaCount",
        )

        # Get scaling activities
        activities = app_autoscaling.describe_scaling_activities(
            ServiceNamespace="rds",
            ResourceId=resource_id,
            ScalableDimension="rds:cluster:ReadReplicaCount",
            MaxResults=5,
        )

        return {
            "cluster": cluster_identifier,
            "scalable_targets": targets.get("ScalableTargets", []),
            "scaling_policies": [{
                "name": p["PolicyName"],
                "type": p["PolicyType"],
                "target_value": p.get("TargetTrackingScalingPolicyConfiguration", {}).get("TargetValue"),
            } for p in policies.get("ScalingPolicies", [])],
            "recent_activities": [{
                "description": a.get("Description", ""),
                "cause": a.get("Cause", ""),
                "status": a.get("StatusCode", ""),
                "time": a.get("StartTime", "").isoformat() if a.get("StartTime") else None,
            } for a in activities.get("ScalingActivities", [])],
        }
    except Exception as e:
        return {"status": "no_autoscaling_configured", "error": str(e)}


@tool
def modify_instance_class(db_instance_identifier: str, new_instance_class: str, apply_immediately: bool = False) -> dict:
    """Scale an RDS/Aurora instance vertically by changing its instance class. REQUIRES APPROVAL.

    This triggers a brief downtime during the modification window unless apply_immediately is True.

    Args:
        db_instance_identifier: The DB instance identifier to scale.
        new_instance_class: New instance class (e.g., 'db.r6g.large', 'db.t3.medium').
        apply_immediately: Apply now (brief downtime) or during next maintenance window.
    """
    import boto3
    rds = boto3.client("rds", region_name=REGION)

    try:
        response = rds.modify_db_instance(
            DBInstanceIdentifier=db_instance_identifier,
            DBInstanceClass=new_instance_class,
            ApplyImmediately=apply_immediately,
        )
        instance = response["DBInstance"]
        return {
            "status": "modifying",
            "instance_id": instance["DBInstanceIdentifier"],
            "current_class": instance.get("DBInstanceClass"),
            "target_class": new_instance_class,
            "apply_immediately": apply_immediately,
            "note": "Immediate" if apply_immediately else "Will apply during next maintenance window",
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def get_instance_details(db_instance_identifier: str) -> dict:
    """Get current instance class, storage, and scaling details for an RDS/Aurora instance.

    Args:
        db_instance_identifier: The DB instance identifier.
    """
    import boto3
    rds = boto3.client("rds", region_name=REGION)

    try:
        response = rds.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)
        instance = response["DBInstances"][0]
        return {
            "instance_id": instance["DBInstanceIdentifier"],
            "instance_class": instance["DBInstanceClass"],
            "engine": instance["Engine"],
            "engine_version": instance["EngineVersion"],
            "status": instance["DBInstanceStatus"],
            "storage_type": instance.get("StorageType"),
            "allocated_storage_gb": instance.get("AllocatedStorage"),
            "max_allocated_storage_gb": instance.get("MaxAllocatedStorage"),
            "multi_az": instance.get("MultiAZ"),
            "publicly_accessible": instance.get("PubliclyAccessible"),
            "endpoint": instance.get("Endpoint", {}).get("Address"),
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ─── Entry Point ────────────────────────────────────────────────────────────────


@app.entrypoint
def invoke(payload, context=None):
    prompt = payload.get("prompt", "")
    user_id = payload.get("user_id", "anonymous")
    if not prompt:
        return {"error": "Missing 'prompt' in payload"}

    # Programmatic Tier-3 gate. Operator decisions arrive in the payload from
    # the calling application, never from model output, and each is bound to a
    # single tool + argument fingerprint.
    tier3 = Tier3ApprovalHook(approvals=payload.get("approvals"), user_id=user_id)

    agent = Agent(
        system_prompt=SYSTEM_PROMPT,
        hooks=[tier3],
        tools=[list_databases, list_tables, get_slow_queries, get_active_sessions,
               get_wait_events, get_vacuum_status, get_index_usage, get_table_bloat,
               get_database_size, get_connections_summary, recommend_index,
               detect_blocking_chains, get_cloudwatch_metrics, check_txid_wraparound,
               create_db_user, drop_db_user, trigger_backup,
               create_index, kill_session, execute_vacuum,
               reindex_concurrently,
               create_read_replica, get_replication_status, clone_to_lower_env,
               setup_data_masking, get_masking_policies, share_data_snapshot,
               replicate_table_with_masking, list_dev_databases,
               configure_aurora_autoscaling, get_autoscaling_status,
               modify_instance_class, get_instance_details,
               execute_sql, execute_sql_on_dev, load_data_from_s3, load_data_from_csv],
    )
    result = agent(prompt)

    # A Tier-3 operation was proposed but is not yet approved. The agent loop
    # stopped before the tool ran; return the pending request for the operator
    # to confirm. Nothing has been executed against the database.
    if getattr(result, "stop_reason", None) == "interrupt":
        return {
            "response": None,
            "awaiting_approval": True,
            "pending_approvals": pending_approvals(result),
            "user_id": user_id,
            "agent_name": "PostgreSQL DB Ops Agent (LIVE)",
            "agent_avatar": "🐘",
        }

    return {"response": result.message, "user_id": user_id, "agent_name": "PostgreSQL DB Ops Agent (LIVE)", "agent_avatar": "🐘"}


if __name__ == "__main__":
    app.run()
