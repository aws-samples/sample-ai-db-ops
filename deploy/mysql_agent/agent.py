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

"""MySQL DB Ops Agent — Real-time operations against Aurora MySQL."""

import os
import json
import logging
import sys
import time
import boto3
import pymysql

# NOTE: BYPASS_TOOL_CONSENT is deliberately NOT set. Tier-3 (mutating) tool
# calls are gated by Tier3ApprovalHook below, which halts the agent loop until
# the operator supplies an explicit APPLY for that exact operation. Setting
# BYPASS_TOOL_CONSENT here would suppress the framework's own consent handling
# and must not be reintroduced.

from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

# Make repo root importable when launched from deploy/mysql_agent/.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.admin_ops.registry.loader import registry  # noqa: E402
from src.admin_ops.db.identifiers import (  # noqa: E402
    validate_identifier,
    validate_column_list,
    quote_mysql,
)
from src.admin_ops.db.cursor_exec import run_cursor  # noqa: E402
from src.admin_ops.db.sql_guard import assert_executable  # noqa: E402
from src.admin_ops.db.statements import (  # noqa: E402
    mysql_create_index,
    mysql_kill,
)
from src.admin_ops.db.tls import mysql_ssl_kwargs  # noqa: E402
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

SECRET_ARN = os.environ.get("MYSQL_SECRET_ARN")
REGION = os.environ.get("AWS_REGION", "us-east-1")

if not SECRET_ARN:
    raise RuntimeError(
        "MYSQL_SECRET_ARN must be set. Create a Secrets Manager secret with "
        "{host, port, username, password, dbname} for your Aurora MySQL cluster "
        "and pass its ARN as the MYSQL_SECRET_ARN env var."
    )


def get_connection():
    """Get a live MySQL connection using credentials from Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=REGION)
    secret = json.loads(client.get_secret_value(SecretId=SECRET_ARN)["SecretString"])
    return pymysql.connect(
        host=secret["host"],
        port=int(secret["port"]),
        user=secret["username"],
        password=secret["password"],
        database=secret["dbname"],
        read_timeout=30,
        cursorclass=pymysql.cursors.DictCursor,
        # Encryption in transit. PyMySQL's implicit default only *prefers* TLS
        # and falls back to cleartext; see src/admin_ops/db/tls.py.
        **mysql_ssl_kwargs(secret["host"]),
    )


SYSTEM_PROMPT = """You are an expert MySQL Database Operations Agent connected to a LIVE Aurora MySQL database.

All tool results are REAL data from the actual database — not simulated.

## Capabilities
- Tier 1 (Read-Only, +10 XP): Schema discovery, slow queries, processlist, InnoDB status, index analysis
- Tier 2 (Advisory, +25 XP): Index recommendations
- Tier 3 (Actioned, +50 XP): CREATE INDEX, KILL connection — REQUIRES APPROVAL

## Rules
1. All data is LIVE. 2. Never execute Tier 3 without approval. 3. Use ALGORITHM=INPLACE when possible.
4. Use emoji: 🟢 OK, 🟡 WARN, 🔴 CRITICAL
"""


@tool
def list_databases() -> dict:
    """List all databases on the MySQL instance with sizes (REAL DATA)."""
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, """
            SELECT table_schema as db_name,
                   ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) as size_mb,
                   COUNT(*) as table_count
            FROM information_schema.tables
            GROUP BY table_schema ORDER BY size_mb DESC;
        """)
        rows = cur.fetchall()
    conn.close()
    return {"databases": rows, "count": len(rows)}


@tool
def list_tables() -> dict:
    """List all tables in the current database with row counts and sizes (REAL DATA)."""
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, """
            SELECT table_name, table_rows,
                   ROUND((data_length + index_length) / 1024 / 1024, 2) as size_mb,
                   ROUND(data_length / 1024 / 1024, 2) as data_mb,
                   ROUND(index_length / 1024 / 1024, 2) as index_mb
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            ORDER BY data_length + index_length DESC;
        """)
        rows = cur.fetchall()
    conn.close()
    return {"tables": rows, "count": len(rows)}


@tool
def get_slow_queries(top_n: int = 10) -> dict:
    """Get slowest queries from performance_schema (REAL DATA).

    Args:
        top_n: Number of queries to return.
    """
    _DEFAULT_BODY = """
            SELECT LEFT(digest_text, 200) as query_text,
                   count_star as calls,
                   ROUND(sum_timer_wait / 1000000000000, 3) as total_time_sec,
                   ROUND(avg_timer_wait / 1000000000000, 3) as avg_time_sec,
                   sum_rows_examined as rows_examined,
                   sum_rows_sent as rows_sent
            FROM performance_schema.events_statements_summary_by_digest
            WHERE schema_name = DATABASE() AND digest_text IS NOT NULL
            ORDER BY avg_timer_wait DESC LIMIT %(top_n)s;
        """
    params = {"top_n": top_n}
    try:
        spec = registry.must_get("my_get_slow_queries")
        rendered = registry.render(spec.template_id, params)
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = params
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, body, params_for_db)
        rows = cur.fetchall()
    conn.close()
    return {"slow_queries": rows, "count": len(rows)}


@tool
def get_processlist() -> dict:
    """Show active connections (SHOW PROCESSLIST equivalent) (REAL DATA)."""
    _DEFAULT_BODY = """
            SELECT id, user, host, db, command, time, state, LEFT(info, 200) as info
            FROM information_schema.processlist
            WHERE command != 'Sleep' ORDER BY time DESC;
        """
    try:
        spec = registry.must_get("my_get_processlist")
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
        rows = cur.fetchall()
    conn.close()
    return {"processes": rows, "active_count": len(rows)}


@tool
def get_innodb_status() -> dict:
    """Report InnoDB engine metrics (REAL DATA)."""
    _DEFAULT_BODY = """
            SELECT variable_name, variable_value FROM performance_schema.global_status
            WHERE variable_name IN (
                'Innodb_buffer_pool_read_requests', 'Innodb_buffer_pool_reads',
                'Innodb_rows_read', 'Innodb_rows_inserted', 'Innodb_rows_updated', 'Innodb_rows_deleted',
                'Innodb_deadlocks', 'Innodb_row_lock_waits', 'Innodb_row_lock_time_avg',
                'Innodb_buffer_pool_pages_total', 'Innodb_buffer_pool_pages_free',
                'Threads_connected', 'Threads_running', 'Uptime'
            );
        """
    try:
        spec = registry.must_get("my_get_innodb_status")
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
        rows = cur.fetchall()
    conn.close()
    metrics = {r["variable_name"]: r["variable_value"] for r in rows}

    # Calculate buffer pool hit rate
    reads_req = int(metrics.get("Innodb_buffer_pool_read_requests", 1))
    reads_disk = int(metrics.get("Innodb_buffer_pool_reads", 0))
    hit_rate = round(100 * (1 - reads_disk / max(reads_req, 1)), 2)

    return {"metrics": metrics, "buffer_pool_hit_rate_pct": hit_rate}


@tool
def get_index_usage() -> dict:
    """Report index usage from sys schema (REAL DATA)."""
    _DEFAULT_BODY = """
            SELECT object_schema, object_name as table_name, index_name,
                   count_star as usage_count, count_read, count_write
            FROM performance_schema.table_io_waits_summary_by_index_usage
            WHERE object_schema = DATABASE() AND index_name IS NOT NULL
            ORDER BY count_star ASC LIMIT 20;
        """
    try:
        spec = registry.must_get("my_get_index_usage")
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
        rows = cur.fetchall()
    conn.close()
    unused = [r for r in rows if r["usage_count"] == 0]
    return {"indexes": rows, "unused_indexes": unused, "unused_count": len(unused)}


@tool
def get_connections_summary() -> dict:
    """Get connection statistics (REAL DATA)."""
    _DEFAULT_BODY = """
            SELECT command as state, COUNT(*) as count
            FROM information_schema.processlist GROUP BY command ORDER BY count DESC;
        """
    try:
        spec = registry.must_get("my_get_connections_summary")
        rendered = registry.render(spec.template_id, {})
        body = rendered.sql
        params_for_db = rendered.params
    except KeyError:
        body = _DEFAULT_BODY
        params_for_db = {}
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, "SELECT @@max_connections as max_conn;")
        max_conn = cur.fetchone()["max_conn"]
        if params_for_db:
            run_cursor(cur, body, params_for_db)
        else:
            run_cursor(cur, body)
        rows = cur.fetchall()
    conn.close()
    total = sum(r["count"] for r in rows)
    return {"connections_by_state": rows, "total": total, "max_connections": max_conn}


@tool
def recommend_index(table_name: str) -> dict:
    """Analyze table and recommend indexes (REAL DATA).

    Args:
        table_name: Table to analyze.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, """
            SELECT index_name, column_name, seq_in_index, non_unique
            FROM information_schema.statistics
            WHERE table_schema = DATABASE() AND table_name = %s
            ORDER BY index_name, seq_in_index;
        """, (table_name,))
        existing = cur.fetchall()

        run_cursor(cur, """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = %s;
        """, (table_name,))
        columns = cur.fetchall()
    conn.close()
    return {"table": table_name, "existing_indexes": existing, "columns": columns}


@tool
def create_index(table_name: str, columns: str, index_name: str) -> dict:
    """Create an index on a MySQL table. REQUIRES APPROVAL.

    Args:
        table_name: Table to index.
        columns: Comma-separated columns.
        index_name: Index name.
    """
    # DDL names identifiers, which no driver can bind. The builder validates and
    # backtick-quotes every identifier so it cannot be skipped here.
    ddl = mysql_create_index(index_name, table_name, columns, inplace=True)
    conn = get_connection()
    import time
    start = time.time()
    with conn.cursor() as cur:
        run_cursor(cur, ddl)
    conn.commit()
    elapsed = round(time.time() - start, 2)
    conn.close()
    return {"status": "success", "ddl": ddl, "duration_seconds": elapsed}


@tool
def kill_connection(connection_id: int) -> dict:
    """Kill a MySQL connection. REQUIRES APPROVAL.

    Args:
        connection_id: Connection ID to kill.
    """
    # MySQL cannot bind the connection id. The builder validates it to a bounded
    # positive integer, so the statement can only ever contain digits.
    stmt = mysql_kill(connection_id)
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, stmt)
    conn.close()
    return {"status": "success", "killed_connection": int(connection_id)}


# ─── Tier 3 — Replicas & Cloning ────────────────────────────────────────────────


@tool
def create_read_replica(source_db_identifier: str, replica_identifier: str, instance_class: str = "db.t3.medium") -> dict:
    """Create a read replica of an Aurora MySQL instance. REQUIRES APPROVAL.

    Args:
        source_db_identifier: Source DB cluster identifier.
        replica_identifier: Identifier for the new replica.
        instance_class: Instance class for the replica.
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
        # (AuroraMySQLCluster, LowerEnvMySQLCluster), so replicas of them are
        # encrypted.
        #
        # If you adapt this call to create a *standalone, non-Aurora* RDS
        # instance — dropping DBClusterIdentifier and using Engine="mysql" —
        # you must pass StorageEncrypted=True explicitly. It defaults to false
        # there, so an otherwise-working copy of this code would create an
        # unencrypted database.
        response = rds.create_db_instance(
            DBInstanceIdentifier=replica_identifier,
            DBClusterIdentifier=source_db_identifier,
            DBInstanceClass=instance_class,
            Engine="aurora-mysql",
            PubliclyAccessible=False,
        )
        instance = response["DBInstance"]
        return {"status": "creating", "replica_id": instance["DBInstanceIdentifier"], "instance_class": instance["DBInstanceClass"]}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def get_replication_status(cluster_identifier: str) -> dict:
    """Check replication status and members for an Aurora MySQL cluster.

    Args:
        cluster_identifier: The Aurora cluster identifier.
    """
    import boto3
    rds = boto3.client("rds", region_name=REGION)
    try:
        response = rds.describe_db_clusters(DBClusterIdentifier=cluster_identifier)
        cluster = response["DBClusters"][0]
        members = [{"instance_id": m["DBInstanceIdentifier"], "is_writer": m["IsClusterWriter"]} for m in cluster.get("DBClusterMembers", [])]
        return {"cluster": cluster_identifier, "status": cluster["Status"], "members": members, "reader_endpoint": cluster.get("ReaderEndpoint")}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def clone_to_lower_env(source_cluster: str, target_cluster_name: str) -> dict:
    """Clone a production Aurora MySQL cluster to a lower environment via snapshot. REQUIRES APPROVAL.

    Args:
        source_cluster: Source Aurora cluster identifier.
        target_cluster_name: Name for the new lower-env cluster.
    """
    import boto3
    from datetime import datetime, timezone
    rds = boto3.client("rds", region_name=REGION)
    snapshot_id = f"{source_cluster}-clone-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    try:
        rds.create_db_cluster_snapshot(DBClusterIdentifier=source_cluster, DBClusterSnapshotIdentifier=snapshot_id)
        return {
            "status": "snapshot_initiated", "snapshot_id": snapshot_id, "target_cluster": target_cluster_name,
            "next_step": f"Restore with: aws rds restore-db-cluster-from-snapshot --db-cluster-identifier {target_cluster_name} --snapshot-identifier {snapshot_id} --engine aurora-mysql",
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
def setup_data_masking(table_name: str, columns_to_mask: str, masking_type: str = "partial") -> dict:
    """Set up data masking on specified columns using MySQL views. REQUIRES APPROVAL.

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
        columns_to_mask: Comma-separated column names to mask.
        masking_type: 'partial' (show first/last chars), 'full' (replace entirely), 'hash' (SHA2).
    """
    conn = get_connection()
    validate_identifier(table_name, kind="table")
    quoted_table = quote_mysql(table_name, kind="table")
    columns = validate_column_list(columns_to_mask)
    masked_view = f"{table_name}_masked"
    quoted_view = quote_mysql(masked_view, kind="view")

    with conn.cursor() as cur:
        run_cursor(cur, "SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s ORDER BY ordinal_position", (table_name,))
        all_cols = [validate_identifier(r["column_name"], kind="column") for r in cur.fetchall()]

        select_parts = []
        for col in all_cols:
            quoted_col = quote_mysql(col, kind="column")
            if col in columns:
                if masking_type == "partial":
                    select_parts.append(f"CONCAT(LEFT({quoted_col}, 2), '****', RIGHT({quoted_col}, 2)) AS {quoted_col}")
                elif masking_type == "full":
                    select_parts.append(f"'*****' AS {quoted_col}")
                else:
                    select_parts.append(f"SHA2({quoted_col}, 256) AS {quoted_col}")
            else:
                select_parts.append(quoted_col)

        # All identifiers are validated + backtick-quoted above (view/table/columns).
        view_sql = f"CREATE OR REPLACE VIEW {quoted_view} AS SELECT {', '.join(select_parts)} FROM {quoted_table}"  # nosec B608
        run_cursor(cur, view_sql)
    conn.commit()
    conn.close()
    return {
        "status": "success",
        "masked_view": masked_view,
        "columns_masked": columns,
        "masking_type": masking_type,
        "compliance_warning": MASKING_COMPLIANCE_WARNING,
    }


@tool
def share_data_snapshot(source_cluster: str, target_account_id: str) -> dict:
    """Share a DB cluster snapshot with another AWS account. REQUIRES APPROVAL.

    Args:
        source_cluster: Source Aurora cluster identifier.
        target_account_id: AWS account ID to share with.
    """
    import boto3
    from datetime import datetime, timezone
    rds = boto3.client("rds", region_name=REGION)
    snapshot_id = f"{source_cluster}-share-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    try:
        rds.create_db_cluster_snapshot(DBClusterIdentifier=source_cluster, DBClusterSnapshotIdentifier=snapshot_id)
        return {
            "status": "snapshot_initiated", "snapshot_id": snapshot_id, "target_account": target_account_id,
            "next_step": f"Once available, share with: aws rds modify-db-cluster-snapshot-attribute --db-cluster-snapshot-identifier {snapshot_id} --attribute-name restore --values-to-add {target_account_id}",
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ─── Tier 1 — Lock Management & Monitoring ───────────────────────────────────────


@tool
def detect_blocking_chains() -> dict:
    """Detect blocking chains in MySQL — shows who is blocking whom."""
    _DEFAULT_BODY = """
            SELECT r.trx_id AS blocked_trx, r.trx_mysql_thread_id AS blocked_pid,
                   LEFT(r.trx_query, 150) AS blocked_query,
                   b.trx_id AS blocking_trx, b.trx_mysql_thread_id AS blocking_pid,
                   LEFT(b.trx_query, 150) AS blocking_query,
                   TIMESTAMPDIFF(SECOND, r.trx_wait_started, NOW()) AS wait_seconds
            FROM information_schema.innodb_lock_waits w
            JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
            JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id
            ORDER BY wait_seconds DESC;
        """
    try:
        spec = registry.must_get("my_detect_blocking_chains")
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
        rows = cur.fetchall()
    conn.close()
    return {"blocking_chains": rows, "count": len(rows), "has_blockers": len(rows) > 0}


@tool
def get_cloudwatch_metrics(instance_identifier: str, period_minutes: int = 60) -> dict:
    """Get CloudWatch metrics for an RDS/Aurora MySQL instance.

    Args:
        instance_identifier: DB instance identifier.
        period_minutes: Lookback period.
    """
    import boto3
    from datetime import datetime, timedelta, timezone
    cw = boto3.client("cloudwatch", region_name=REGION)
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=period_minutes)
    metrics_to_get = ["CPUUtilization", "FreeableMemory", "ReadIOPS", "WriteIOPS", "FreeStorageSpace", "DatabaseConnections"]
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
    return {"instance": instance_identifier, "metrics": results}


@tool
def create_db_user(username: str, password: str, readonly: bool = True) -> dict:
    """Create a MySQL user. REQUIRES APPROVAL.

    Args:
        username: New username.
        password: Password.
        readonly: If True, grants SELECT only.
    """
    username = validate_identifier(username, kind="user")
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, "CREATE USER %s@'%%' IDENTIFIED BY %s", (username, password))
        if readonly:
            run_cursor(cur, "GRANT SELECT ON appdb.* TO %s@'%%'", (username,))
        else:
            run_cursor(cur, "GRANT ALL PRIVILEGES ON appdb.* TO %s@'%%'", (username,))
        run_cursor(cur, "FLUSH PRIVILEGES")
    conn.commit()
    conn.close()
    return {"status": "success", "username": username, "readonly": readonly}


@tool
def drop_db_user(username: str) -> dict:
    """Drop a MySQL user. REQUIRES APPROVAL.

    Args:
        username: Username to drop.
    """
    username = validate_identifier(username, kind="user")
    conn = get_connection()
    with conn.cursor() as cur:
        run_cursor(cur, "DROP USER IF EXISTS %s@'%%'", (username,))
    conn.commit()
    conn.close()
    return {"status": "success", "dropped": username}


@tool
def trigger_backup(cluster_identifier: str) -> dict:
    """Trigger an on-demand snapshot of the Aurora MySQL cluster. REQUIRES APPROVAL.

    Args:
        cluster_identifier: Cluster identifier.
    """
    import boto3
    from datetime import datetime, timezone
    rds = boto3.client("rds", region_name=REGION)
    snapshot_id = f"{cluster_identifier}-manual-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    try:
        rds.create_db_cluster_snapshot(DBClusterIdentifier=cluster_identifier, DBClusterSnapshotIdentifier=snapshot_id)
        return {"status": "initiated", "snapshot_id": snapshot_id}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ─── Tier 3 — DDL & Data Operations ─────────────────────────────────────────────


@tool
def execute_sql(sql: str) -> dict:
    """Execute an arbitrary SQL statement against the production MySQL database. REQUIRES APPROVAL.

    Args:
        sql: The SQL statement to execute.
    """
    # Defense in depth beneath the Tier-3 approval gate: refuse stacked
    # statements (which could smuggle an unapproved second statement past a
    # fingerprinted approval) and refuse constructs that reach outside the
    # database, such as LOAD_FILE or INTO OUTFILE.
    assert_executable(sql)
    sql = sql.strip().rstrip(";").strip()
    conn = get_connection()
    import time
    start = time.time()
    with conn.cursor() as cur:
        run_cursor(cur, sql)
        elapsed = round(time.time() - start, 2)
        if cur.description:
            rows = cur.fetchall()
            conn.close()
            return {"status": "success", "rows": rows, "count": len(rows), "duration_seconds": elapsed}
        else:
            rowcount = cur.rowcount
            conn.commit()
            conn.close()
            return {"status": "success", "rows_affected": rowcount, "sql": sql[:200], "duration_seconds": elapsed}


@tool
def load_data_from_s3(table_name: str, s3_uri: str) -> dict:
    """Load data from an S3 file (CSV/JSON) into a MySQL table. REQUIRES APPROVAL.

    Args:
        table_name: Target table.
        s3_uri: S3 URI (e.g., s3://bucket/path/file.csv).
    """
    import boto3
    import csv
    import io

    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket, key = parts[0], parts[1]

    # Encryption is already covered on both legs and needs no extra parameters:
    # in transit, boto3 talks to S3 over HTTPS by default; at rest, every object
    # is encrypted with SSE-S3 (AES-256) unless the bucket specifies a different
    # key, which S3 has applied to new objects by default since January 2023.
    # GetObject decrypts transparently for a caller with permission on the
    # object and, for SSE-KMS buckets, on the key. To *require* a particular
    # scheme rather than accept the default, enforce it on the bucket with a
    # policy condition on s3:x-amz-server-side-encryption.
    s3 = boto3.client("s3", region_name=REGION)
    content = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")

    quoted_table = quote_mysql(table_name, kind="table")
    conn = get_connection()
    rows_inserted = 0

    if key.endswith(".json"):
        import json as json_mod
        items = json_mod.loads(content)
        if not isinstance(items, list):
            items = items.get("Items", items.get("items", [items]))
        if items:
            headers = list(items[0].keys())
            validated_headers = validate_column_list(headers)
            with conn.cursor() as cur:
                placeholders = ", ".join(["%s"] * len(validated_headers))
                col_names = ", ".join(quote_mysql(h, kind="column") for h in validated_headers)
                # table + columns validated/backtick-quoted; values are bound %s.
                insert_sql = f"INSERT INTO {quoted_table} ({col_names}) VALUES ({placeholders})"  # nosec B608
                for item in items:
                    values = [str(item.get(h, "")) for h in validated_headers]
                    run_cursor(cur, insert_sql, values)
                    rows_inserted += 1
    else:
        reader = csv.reader(io.StringIO(content))
        headers = next(reader)
        validated_headers = validate_column_list(headers)
        with conn.cursor() as cur:
            placeholders = ", ".join(["%s"] * len(validated_headers))
            col_names = ", ".join(quote_mysql(h, kind="column") for h in validated_headers)
            # table + columns validated/backtick-quoted; values are bound %s.
            insert_sql = f"INSERT INTO {quoted_table} ({col_names}) VALUES ({placeholders})"  # nosec B608
            for row in reader:
                if row:
                    run_cursor(cur, insert_sql, row)
                    rows_inserted += 1
    conn.commit()
    conn.close()
    return {"status": "success", "table": table_name, "s3_uri": s3_uri, "rows_inserted": rows_inserted}


@tool
def load_data_from_csv(table_name: str, csv_data: str) -> dict:
    """Load CSV data into a MySQL table. REQUIRES APPROVAL.

    Args:
        table_name: Target table.
        csv_data: CSV content (first row = headers).
    """
    import csv
    import io

    quoted_table = quote_mysql(table_name, kind="table")
    conn = get_connection()
    reader = csv.reader(io.StringIO(csv_data))
    headers = next(reader)
    validated_headers = validate_column_list(headers)
    rows_inserted = 0

    with conn.cursor() as cur:
        placeholders = ", ".join(["%s"] * len(validated_headers))
        col_names = ", ".join(quote_mysql(h, kind="column") for h in validated_headers)
        # table + columns validated/backtick-quoted; values are bound %s.
        insert_sql = f"INSERT INTO {quoted_table} ({col_names}) VALUES ({placeholders})"  # nosec B608
        for row in reader:
            run_cursor(cur, insert_sql, row)
            rows_inserted += 1
    conn.commit()
    conn.close()
    return {"status": "success", "table": table_name, "rows_inserted": rows_inserted, "columns": headers}


# ─── Tier 3 — Auto Scaling & Instance Scaling ────────────────────────────────────


@tool
def configure_aurora_autoscaling(cluster_identifier: str, min_replicas: int = 1, max_replicas: int = 4, target_cpu: int = 70) -> dict:
    """Configure Aurora Auto Scaling for read replicas based on CPU. REQUIRES APPROVAL.

    Args:
        cluster_identifier: Aurora cluster identifier.
        min_replicas: Minimum read replicas.
        max_replicas: Maximum read replicas.
        target_cpu: Target CPU % to maintain.
    """
    import boto3
    app_as = boto3.client("application-autoscaling", region_name=REGION)
    resource_id = f"cluster:{cluster_identifier}"
    try:
        app_as.register_scalable_target(
            ServiceNamespace="rds", ResourceId=resource_id,
            ScalableDimension="rds:cluster:ReadReplicaCount",
            MinCapacity=min_replicas, MaxCapacity=max_replicas,
        )
        policy_name = f"{cluster_identifier}-cpu-scaling"
        app_as.put_scaling_policy(
            PolicyName=policy_name, ServiceNamespace="rds",
            ResourceId=resource_id, ScalableDimension="rds:cluster:ReadReplicaCount",
            PolicyType="TargetTrackingScaling",
            TargetTrackingScalingPolicyConfiguration={
                "TargetValue": float(target_cpu),
                "PredefinedMetricSpecification": {"PredefinedMetricType": "RDSReaderAverageCPUUtilization"},
                "ScaleInCooldown": 300, "ScaleOutCooldown": 300,
            },
        )
        return {"status": "success", "cluster": cluster_identifier, "policy": policy_name,
                "min": min_replicas, "max": max_replicas, "target_cpu": target_cpu}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def get_autoscaling_status(cluster_identifier: str) -> dict:
    """Check Aurora Auto Scaling configuration and recent activity.

    Args:
        cluster_identifier: Aurora cluster identifier.
    """
    import boto3
    app_as = boto3.client("application-autoscaling", region_name=REGION)
    resource_id = f"cluster:{cluster_identifier}"
    try:
        targets = app_as.describe_scalable_targets(ServiceNamespace="rds", ResourceIds=[resource_id], ScalableDimension="rds:cluster:ReadReplicaCount")
        policies = app_as.describe_scaling_policies(ServiceNamespace="rds", ResourceId=resource_id, ScalableDimension="rds:cluster:ReadReplicaCount")
        return {
            "cluster": cluster_identifier,
            "targets": targets.get("ScalableTargets", []),
            "policies": [{"name": p["PolicyName"], "target": p.get("TargetTrackingScalingPolicyConfiguration", {}).get("TargetValue")} for p in policies.get("ScalingPolicies", [])],
        }
    except Exception as e:
        return {"status": "no_autoscaling", "error": str(e)}


@tool
def modify_instance_class(db_instance_identifier: str, new_instance_class: str, apply_immediately: bool = False) -> dict:
    """Scale an instance vertically by changing its class. REQUIRES APPROVAL.

    Args:
        db_instance_identifier: Instance to scale.
        new_instance_class: Target class (e.g., 'db.r6g.large').
        apply_immediately: Apply now or during maintenance window.
    """
    import boto3
    rds = boto3.client("rds", region_name=REGION)
    try:
        response = rds.modify_db_instance(DBInstanceIdentifier=db_instance_identifier, DBInstanceClass=new_instance_class, ApplyImmediately=apply_immediately)
        return {"status": "modifying", "instance": db_instance_identifier, "target_class": new_instance_class, "immediate": apply_immediately}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def get_instance_details(db_instance_identifier: str) -> dict:
    """Get instance class, storage, and status details.

    Args:
        db_instance_identifier: Instance identifier.
    """
    import boto3
    rds = boto3.client("rds", region_name=REGION)
    try:
        response = rds.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)
        i = response["DBInstances"][0]
        return {"instance_id": i["DBInstanceIdentifier"], "class": i["DBInstanceClass"], "engine": i["Engine"],
                "status": i["DBInstanceStatus"], "storage_gb": i.get("AllocatedStorage"), "multi_az": i.get("MultiAZ")}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


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
        tools=[list_databases, list_tables, get_slow_queries, get_processlist,
               get_innodb_status, get_index_usage, get_connections_summary,
               detect_blocking_chains, get_cloudwatch_metrics,
               recommend_index, create_index, kill_connection,
               create_db_user, drop_db_user, trigger_backup,
               create_read_replica, get_replication_status, clone_to_lower_env,
               setup_data_masking, share_data_snapshot,
               configure_aurora_autoscaling, get_autoscaling_status,
               modify_instance_class, get_instance_details,
               execute_sql, load_data_from_s3, load_data_from_csv],
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
            "agent_name": "MySQL DB Ops Agent (LIVE)",
            "agent_avatar": "🐬",
        }

    return {"response": result.message, "user_id": user_id, "agent_name": "MySQL DB Ops Agent (LIVE)", "agent_avatar": "🐬"}


if __name__ == "__main__":
    app.run()
