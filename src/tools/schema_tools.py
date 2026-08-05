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

"""Schema discovery tools — Tier 1 (read-only)."""

from strands import tool

from src.tools._helpers import get_connection, get_registry_entry


@tool
def list_databases(db_identifier: str) -> dict:
    """List all databases on the specified database instance.

    Args:
        db_identifier: The database identifier from the fleet registry.

    Returns:
        A dict with the list of database names and metadata.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname, pg_database_size(datname) as size_bytes "
                "FROM pg_database WHERE datistemplate = false ORDER BY datname;"
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {"db_identifier": db_identifier, "engine": engine, "databases": rows}

    elif "mysql" in engine:
        with conn.cursor() as cur:
            cur.execute("SHOW DATABASES;")
            rows = cur.fetchall()
        return {"db_identifier": db_identifier, "engine": engine, "databases": rows}

    return {"error": f"list_databases not implemented for engine: {engine}"}


@tool
def list_tables(db_identifier: str, schema_name: str = "public") -> dict:
    """List all tables in the specified schema/database.

    Args:
        db_identifier: The database identifier from the fleet registry.
        schema_name: Schema name (default 'public' for PostgreSQL).

    Returns:
        A dict with table names, row estimates, and sizes.
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
                    tablename,
                    pg_total_relation_size(schemaname || '.' || tablename) as total_bytes,
                    n_live_tup as estimated_rows
                FROM pg_stat_user_tables
                WHERE schemaname = %s
                ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC;
                """,
                (schema_name,),
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {
            "db_identifier": db_identifier,
            "schema": schema_name,
            "tables": rows,
        }

    elif "mysql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, table_rows, data_length + index_length as total_bytes
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                ORDER BY data_length + index_length DESC;
                """
            )
            rows = cur.fetchall()
        return {"db_identifier": db_identifier, "tables": rows}

    return {"error": f"list_tables not implemented for engine: {engine}"}


@tool
def describe_table(db_identifier: str, table_name: str, schema_name: str = "public") -> dict:
    """Describe the schema of a specific table including columns, types, and constraints.

    Args:
        db_identifier: The database identifier from the fleet registry.
        table_name: Name of the table to describe.
        schema_name: Schema name (default 'public').

    Returns:
        A dict with column definitions, constraints, and indexes.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            # Columns
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default,
                       character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position;
                """,
                (schema_name, table_name),
            )
            columns = [desc[0] for desc in cur.description]
            col_rows = [dict(zip(columns, row)) for row in cur.fetchall()]

            # Indexes
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = %s AND tablename = %s;
                """,
                (schema_name, table_name),
            )
            idx_columns = [desc[0] for desc in cur.description]
            idx_rows = [dict(zip(idx_columns, row)) for row in cur.fetchall()]

            # Constraints
            cur.execute(
                """
                SELECT conname, contype, pg_get_constraintdef(oid) as definition
                FROM pg_constraint
                WHERE conrelid = %s::regclass;
                """,
                (f"{schema_name}.{table_name}",),
            )
            con_columns = [desc[0] for desc in cur.description]
            con_rows = [dict(zip(con_columns, row)) for row in cur.fetchall()]

        return {
            "db_identifier": db_identifier,
            "table": table_name,
            "schema": schema_name,
            "columns": col_rows,
            "indexes": idx_rows,
            "constraints": con_rows,
        }

    return {"error": f"describe_table not implemented for engine: {engine}"}


@tool
def show_relationships(db_identifier: str, schema_name: str = "public") -> dict:
    """Show foreign key relationships between tables in the schema.

    Args:
        db_identifier: The database identifier from the fleet registry.
        schema_name: Schema name (default 'public').

    Returns:
        A dict with foreign key relationships.
    """
    entry = get_registry_entry(db_identifier)
    conn = get_connection(entry)
    engine = entry.engine.value

    if "postgresql" in engine:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    tc.table_name as source_table,
                    kcu.column_name as source_column,
                    ccu.table_name as target_table,
                    ccu.column_name as target_column,
                    tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = %s
                ORDER BY tc.table_name;
                """,
                (schema_name,),
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {
            "db_identifier": db_identifier,
            "schema": schema_name,
            "relationships": rows,
        }

    return {"error": f"show_relationships not implemented for engine: {engine}"}
