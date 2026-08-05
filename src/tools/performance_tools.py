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

"""Performance monitoring tools — Tier 1 (read-only)."""

from strands import tool
import boto3

from src.config import settings
from src.tools._helpers import get_connection, get_registry_entry


@tool
def get_slow_queries(db_identifier: str, top_n: int = 10) -> dict:
    """Retrieve the top N slowest queries from the specified database.

    Args:
        db_identifier: The database identifier from the fleet registry.
        top_n: Number of slow queries to return (default 10).

    Returns:
        A dict with the slowest queries, their execution stats, and call counts.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    queryid,
                    LEFT(query, 200) as query_text,
                    calls,
                    total_exec_time / 1000.0 as total_time_sec,
                    mean_exec_time / 1000.0 as avg_time_sec,
                    rows,
                    shared_blks_hit + shared_blks_read as total_blocks
                FROM pg_stat_statements
                WHERE userid != 10  -- exclude system
                ORDER BY mean_exec_time DESC
                LIMIT %s;
                """,
                (top_n,),
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "slow_queries": rows,
            "count": len(rows),
        }

    elif "mysql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    digest_text as query_text,
                    count_star as calls,
                    ROUND(sum_timer_wait / 1000000000000, 3) as total_time_sec,
                    ROUND(avg_timer_wait / 1000000000000, 3) as avg_time_sec,
                    sum_rows_examined as rows_examined
                FROM performance_schema.events_statements_summary_by_digest
                WHERE schema_name = DATABASE()
                ORDER BY avg_timer_wait DESC
                LIMIT %s;
                """,
                (top_n,),
            )
            rows = cur.fetchall()
        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "slow_queries": rows,
            "count": len(rows),
        }

    return {"error": f"get_slow_queries not implemented for engine: {engine}"}


@tool
def get_active_sessions(db_identifier: str) -> dict:
    """Show current active sessions and their state on the database.

    Args:
        db_identifier: The database identifier from the fleet registry.

    Returns:
        A dict with active sessions including PID, state, query, and duration.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pid,
                    usename,
                    application_name,
                    client_addr::text,
                    state,
                    wait_event_type,
                    wait_event,
                    LEFT(query, 200) as query_text,
                    EXTRACT(EPOCH FROM (now() - query_start))::int as duration_sec,
                    query_start::text
                FROM pg_stat_activity
                WHERE state != 'idle'
                    AND pid != pg_backend_pid()
                ORDER BY query_start ASC;
                """
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "active_sessions": rows,
            "total_active": len(rows),
        }

    elif "mysql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id as pid,
                    user as usename,
                    host as client_addr,
                    db as database_name,
                    command as state,
                    time as duration_sec,
                    LEFT(info, 200) as query_text
                FROM information_schema.processlist
                WHERE command != 'Sleep'
                ORDER BY time DESC;
                """
            )
            rows = cur.fetchall()
        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "active_sessions": rows,
            "total_active": len(rows),
        }

    return {"error": f"get_active_sessions not implemented for engine: {engine}"}


@tool
def get_wait_events(db_identifier: str) -> dict:
    """Report wait statistics and wait event types for the database.

    Args:
        db_identifier: The database identifier from the fleet registry.

    Returns:
        A dict with wait events grouped by type, with counts and total wait time.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    wait_event_type,
                    wait_event,
                    COUNT(*) as session_count,
                    SUM(EXTRACT(EPOCH FROM (now() - query_start)))::int as total_wait_sec
                FROM pg_stat_activity
                WHERE state != 'idle'
                    AND wait_event IS NOT NULL
                    AND pid != pg_backend_pid()
                GROUP BY wait_event_type, wait_event
                ORDER BY session_count DESC;
                """
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "wait_events": rows,
        }

    return {"error": f"get_wait_events not implemented for engine: {engine}"}


@tool
def get_cloudwatch_metrics(
    db_identifier: str, metric_names: list[str] | None = None, period_minutes: int = 60
) -> dict:
    """Retrieve CloudWatch metrics for the database instance.

    Args:
        db_identifier: The database identifier from the fleet registry.
        metric_names: List of metric names to retrieve. Defaults to CPU, FreeableMemory, ReadIOPS, WriteIOPS, DatabaseConnections.
        period_minutes: Time period to look back in minutes (default 60).

    Returns:
        A dict with metric data points for the requested period.
    """
    entry = get_registry_entry(db_identifier)

    if metric_names is None:
        metric_names = [
            "CPUUtilization",
            "FreeableMemory",
            "ReadIOPS",
            "WriteIOPS",
            "DatabaseConnections",
        ]

    cloudwatch = boto3.client("cloudwatch", region_name=settings.aws_region)

    from datetime import datetime, timedelta, timezone

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=period_minutes)

    # Determine namespace based on engine
    engine = entry.engine.value
    if "dynamodb" in engine:
        namespace = "AWS/DynamoDB"
        dimension_name = "TableName"
    elif "redshift" in engine:
        namespace = "AWS/Redshift"
        dimension_name = "ClusterIdentifier"
    elif "elasticache" in engine:
        namespace = "AWS/ElastiCache"
        dimension_name = "CacheClusterId"
    else:
        namespace = "AWS/RDS"
        dimension_name = "DBInstanceIdentifier"

    metrics_data = {}
    for metric_name in metric_names:
        try:
            response = cloudwatch.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=[
                    {"Name": dimension_name, "Value": db_identifier},
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,  # 5-minute intervals
                Statistics=["Average", "Maximum"],
            )
            datapoints = sorted(response["Datapoints"], key=lambda x: x["Timestamp"])
            metrics_data[metric_name] = [
                {
                    "timestamp": dp["Timestamp"].isoformat(),
                    "average": dp.get("Average"),
                    "maximum": dp.get("Maximum"),
                }
                for dp in datapoints
            ]
        except Exception as e:
            metrics_data[metric_name] = {"error": str(e)}

    return {
        "db_identifier": db_identifier,
        "engine": engine,
        "period_minutes": period_minutes,
        "metrics": metrics_data,
    }
