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

"""Agent tools — database operations exposed via @tool decorator."""

from src.tools.schema_tools import (
    describe_table,
    list_databases,
    list_tables,
    show_relationships,
)
from src.tools.performance_tools import (
    get_active_sessions,
    get_cloudwatch_metrics,
    get_slow_queries,
    get_wait_events,
)
from src.tools.index_tools import (
    get_execution_plan,
    get_index_usage,
    get_missing_indexes,
    get_table_bloat,
)
from src.tools.maintenance_tools import (
    get_backup_status,
    get_vacuum_status,
)
from src.tools.advisory_tools import (
    recommend_capacity_change,
    recommend_index,
)
from src.tools.action_tools import (
    create_index,
    drop_index,
    execute_vacuum,
    kill_session,
    trigger_backup,
)
from src.tools.gamification_tools import (
    get_active_quests,
    get_database_health_score,
    get_leaderboard,
    get_user_profile,
)

__all__ = [
    # Tier 1 — Schema Discovery
    "list_databases",
    "list_tables",
    "describe_table",
    "show_relationships",
    # Tier 1 — Performance Monitoring
    "get_slow_queries",
    "get_active_sessions",
    "get_wait_events",
    "get_cloudwatch_metrics",
    # Tier 1 — Index Analysis
    "get_missing_indexes",
    "get_index_usage",
    "get_execution_plan",
    "get_table_bloat",
    # Tier 1 — Maintenance
    "get_vacuum_status",
    "get_backup_status",
    # Tier 2 — Advisory
    "recommend_index",
    "recommend_capacity_change",
    # Tier 3 — Actioned
    "create_index",
    "drop_index",
    "execute_vacuum",
    "kill_session",
    "trigger_backup",
    # Gamification
    "get_user_profile",
    "get_leaderboard",
    "get_active_quests",
    "get_database_health_score",
]
