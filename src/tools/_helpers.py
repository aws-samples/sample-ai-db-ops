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

"""Shared helpers for tool implementations."""

from typing import Any

from src.connections.manager import ConnectionManager
from src.registry.models import DatabaseEntry
from src.registry.repository import DatabaseRegistry

# Module-level singletons (initialized once per session)
_registry: DatabaseRegistry | None = None
_connection_manager: ConnectionManager | None = None


def get_registry() -> DatabaseRegistry:
    """Get or create the database registry singleton."""
    global _registry
    if _registry is None:
        _registry = DatabaseRegistry()
    return _registry


def get_connection_manager() -> ConnectionManager:
    """Get or create the connection manager singleton."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager


def get_registry_entry(db_identifier: str) -> DatabaseEntry:
    """Retrieve a database entry from the registry, raising if not found."""
    registry = get_registry()
    entry = registry.get(db_identifier)
    if entry is None:
        raise ValueError(
            f"Database '{db_identifier}' not found in registry. "
            f"Use list_databases to see available databases."
        )
    return entry


def get_connection(entry: DatabaseEntry) -> Any:
    """Get a read-only connection for the given database entry."""
    mgr = get_connection_manager()
    return mgr.get_readonly_connection(entry)


def get_privileged_connection(entry: DatabaseEntry) -> Any:
    """Get a privileged connection for Tier 3 operations."""
    mgr = get_connection_manager()
    return mgr.get_privileged_connection(entry)


# Tool tier classification
TIER_MAP: dict[str, int] = {
    # Tier 1 — Read-only
    "list_databases": 1,
    "list_tables": 1,
    "describe_table": 1,
    "show_relationships": 1,
    "get_slow_queries": 1,
    "get_active_sessions": 1,
    "get_wait_events": 1,
    "get_cloudwatch_metrics": 1,
    "get_missing_indexes": 1,
    "get_index_usage": 1,
    "get_execution_plan": 1,
    "get_table_bloat": 1,
    "get_vacuum_status": 1,
    "get_backup_status": 1,
    "get_user_profile": 1,
    "get_leaderboard": 1,
    "get_active_quests": 1,
    "get_database_health_score": 1,
    # Tier 2 — Advisory
    "recommend_index": 2,
    "recommend_query_rewrite": 2,
    "recommend_capacity_change": 2,
    # Tier 3 — Actioned (requires approval)
    "create_index": 3,
    "drop_index": 3,
    "execute_vacuum": 3,
    "kill_session": 3,
    "trigger_backup": 3,
}


def get_tool_tier(tool_name: str) -> int:
    """Get the tier level for a tool. Defaults to 1 (read-only)."""
    return TIER_MAP.get(tool_name, 1)
