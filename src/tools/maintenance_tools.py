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

"""Maintenance operation tools — Tier 1 (read-only status checks)."""

from strands import tool
import boto3

from src.config import settings
from src.tools._helpers import get_connection, get_registry_entry


@tool
def get_vacuum_status(db_identifier: str) -> dict:
    """Report vacuum/autovacuum status and dead tuple counts for PostgreSQL.

    Args:
        db_identifier: The database identifier from the fleet registry.

    Returns:
        A dict with vacuum status per table including last vacuum time and dead tuples.
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
                    END as dead_pct,
                    last_vacuum::text,
                    last_autovacuum::text,
                    vacuum_count,
                    autovacuum_count,
                    last_analyze::text,
                    last_autoanalyze::text
                FROM pg_stat_user_tables
                ORDER BY n_dead_tup DESC
                LIMIT 30;
                """
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]

            # Check for currently running vacuums
            cur.execute(
                """
                SELECT
                    pid,
                    relid::regclass::text as table_name,
                    phase,
                    heap_blks_total,
                    heap_blks_scanned,
                    CASE WHEN heap_blks_total > 0
                        THEN ROUND(100.0 * heap_blks_scanned / heap_blks_total, 1)
                        ELSE 0
                    END as progress_pct
                FROM pg_stat_progress_vacuum;
                """
            )
            vac_columns = [desc[0] for desc in cur.description]
            running_vacuums = [dict(zip(vac_columns, row)) for row in cur.fetchall()]

        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "vacuum_status": rows,
            "running_vacuums": running_vacuums,
            "tables_needing_vacuum": [r for r in rows if r["dead_pct"] > 10],
        }

    return {"error": f"get_vacuum_status not implemented for engine: {engine}"}


@tool
def get_backup_status(db_identifier: str) -> dict:
    """Report backup status and last successful backup for the database.

    Args:
        db_identifier: The database identifier from the fleet registry.

    Returns:
        A dict with automated backup info and snapshot details.
    """
    entry = get_registry_entry(db_identifier)
    engine = entry.engine.value

    rds = boto3.client("rds", region_name=settings.aws_region)

    if "postgresql" in engine or "mysql" in engine or "sqlserver" in engine:
        try:
            # Get DB instance details for backup info
            response = rds.describe_db_instances(
                DBInstanceIdentifier=db_identifier
            )
            instance = response["DBInstances"][0]

            backup_info = {
                "backup_retention_period": instance.get("BackupRetentionPeriod"),
                "preferred_backup_window": instance.get("PreferredBackupWindow"),
                "latest_restorable_time": (
                    instance.get("LatestRestorableTime").isoformat()
                    if instance.get("LatestRestorableTime")
                    else None
                ),
            }

            # Get recent snapshots
            snap_response = rds.describe_db_snapshots(
                DBInstanceIdentifier=db_identifier,
                SnapshotType="automated",
                MaxRecords=5,
            )
            snapshots = [
                {
                    "snapshot_id": s["DBSnapshotIdentifier"],
                    "status": s["Status"],
                    "created": s["SnapshotCreateTime"].isoformat(),
                    "size_gb": s.get("AllocatedStorage"),
                }
                for s in snap_response.get("DBSnapshots", [])
            ]

            return {
                "db_identifier": db_identifier,
                "engine": engine,
                "backup_config": backup_info,
                "recent_snapshots": snapshots,
            }
        except Exception as e:
            return {
                "db_identifier": db_identifier,
                "engine": engine,
                "error": str(e),
            }

    return {"error": f"get_backup_status not implemented for engine: {engine}"}
