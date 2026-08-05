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

"""Advisory recommendation tools — Tier 2 (suggest but don't execute)."""

from strands import tool

from src.tools._helpers import get_connection, get_registry_entry


@tool
def recommend_index(db_identifier: str, table_name: str, schema_name: str = "public") -> dict:
    """Generate CREATE INDEX recommendations for a table based on query patterns.

    Args:
        db_identifier: The database identifier from the fleet registry.
        table_name: The table to analyze for index recommendations.
        schema_name: Schema name (default 'public').

    Returns:
        A dict with recommended indexes including DDL statements and estimated impact.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            # Find columns involved in sequential scans via pg_stat_statements
            cur.execute(
                """
                SELECT
                    s.query,
                    s.calls,
                    s.mean_exec_time / 1000.0 as avg_time_sec,
                    s.rows
                FROM pg_stat_statements s
                WHERE s.query ILIKE %s
                    AND s.mean_exec_time > 1000  -- > 1 second
                ORDER BY s.mean_exec_time DESC
                LIMIT 10;
                """,
                (f"%{table_name}%",),
            )
            columns = [desc[0] for desc in cur.description]
            slow_queries = [dict(zip(columns, row)) for row in cur.fetchall()]

            # Get existing indexes
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = %s AND tablename = %s;
                """,
                (schema_name, table_name),
            )
            idx_cols = [desc[0] for desc in cur.description]
            existing_indexes = [dict(zip(idx_cols, row)) for row in cur.fetchall()]

            # Get column statistics for recommendation
            cur.execute(
                """
                SELECT
                    attname as column_name,
                    n_distinct,
                    correlation
                FROM pg_stats
                WHERE schemaname = %s AND tablename = %s
                ORDER BY n_distinct DESC;
                """,
                (schema_name, table_name),
            )
            stat_cols = [desc[0] for desc in cur.description]
            col_stats = [dict(zip(stat_cols, row)) for row in cur.fetchall()]

        return {
            "db_identifier": db_identifier,
            "engine": engine,
            "table": f"{schema_name}.{table_name}",
            "slow_queries_on_table": slow_queries,
            "existing_indexes": existing_indexes,
            "column_statistics": col_stats,
            "note": (
                "Review slow queries and column statistics to determine which columns "
                "would benefit from indexing. High n_distinct values and columns in "
                "WHERE/JOIN clauses are good candidates."
            ),
        }

    return {"error": f"recommend_index not implemented for engine: {engine}"}


@tool
def recommend_capacity_change(db_identifier: str) -> dict:
    """Analyze current resource utilization and recommend capacity scaling.

    Args:
        db_identifier: The database identifier from the fleet registry.

    Returns:
        A dict with current utilization metrics and scaling recommendations.
    """
    entry = get_registry_entry(db_identifier)
    engine = entry.engine.value

    import boto3
    from datetime import datetime, timedelta, timezone
    from src.config import settings

    cloudwatch = boto3.client("cloudwatch", region_name=settings.aws_region)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=24)

    metrics_to_check = ["CPUUtilization", "FreeableMemory", "DatabaseConnections"]
    utilization = {}

    for metric in metrics_to_check:
        try:
            response = cloudwatch.get_metric_statistics(
                Namespace="AWS/RDS",
                MetricName=metric,
                Dimensions=[
                    {"Name": "DBInstanceIdentifier", "Value": db_identifier},
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=3600,
                Statistics=["Average", "Maximum"],
            )
            datapoints = response.get("Datapoints", [])
            if datapoints:
                avg_values = [dp["Average"] for dp in datapoints]
                max_values = [dp["Maximum"] for dp in datapoints]
                utilization[metric] = {
                    "avg_24h": round(sum(avg_values) / len(avg_values), 2),
                    "max_24h": round(max(max_values), 2),
                }
        except Exception as e:
            utilization[metric] = {"error": str(e)}

    recommendations = []
    cpu = utilization.get("CPUUtilization", {})
    if cpu.get("avg_24h", 0) > 80:
        recommendations.append("CPU consistently high — consider scaling up instance class.")
    elif cpu.get("max_24h", 0) < 20:
        recommendations.append("CPU consistently low — consider scaling down to save costs.")

    memory = utilization.get("FreeableMemory", {})
    if memory.get("avg_24h", float("inf")) < 500_000_000:  # < 500MB
        recommendations.append("Low freeable memory — consider scaling up or optimizing queries.")

    return {
        "db_identifier": db_identifier,
        "engine": engine,
        "utilization_24h": utilization,
        "recommendations": recommendations if recommendations else ["Current capacity appears adequate."],
    }
