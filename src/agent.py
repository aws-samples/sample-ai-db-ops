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

"""Main agent definition — Strands Agent with tools, hooks, and configuration."""

import logging

from strands import Agent
from strands.models import BedrockModel

from src.config import settings
from src.prompts import DBOPS_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _load_tools() -> list:
    """Load all available tools. Gracefully handles missing DB drivers."""
    tools = []

    try:
        from src.tools.schema_tools import (
            describe_table,
            list_databases,
            list_tables,
            show_relationships,
        )
        tools.extend([list_databases, list_tables, describe_table, show_relationships])
    except Exception as e:
        logger.warning(f"Schema tools unavailable: {e}")

    try:
        from src.tools.performance_tools import (
            get_active_sessions,
            get_cloudwatch_metrics,
            get_slow_queries,
            get_wait_events,
        )
        tools.extend([get_slow_queries, get_active_sessions, get_wait_events, get_cloudwatch_metrics])
    except Exception as e:
        logger.warning(f"Performance tools unavailable: {e}")

    try:
        from src.tools.index_tools import (
            get_execution_plan,
            get_index_usage,
            get_missing_indexes,
            get_table_bloat,
        )
        tools.extend([get_missing_indexes, get_index_usage, get_execution_plan, get_table_bloat])
    except Exception as e:
        logger.warning(f"Index tools unavailable: {e}")

    try:
        from src.tools.maintenance_tools import get_backup_status, get_vacuum_status
        tools.extend([get_vacuum_status, get_backup_status])
    except Exception as e:
        logger.warning(f"Maintenance tools unavailable: {e}")

    try:
        from src.tools.advisory_tools import recommend_capacity_change, recommend_index
        tools.extend([recommend_index, recommend_capacity_change])
    except Exception as e:
        logger.warning(f"Advisory tools unavailable: {e}")

    try:
        from src.tools.action_tools import (
            create_index,
            drop_index,
            execute_vacuum,
            kill_session,
            trigger_backup,
        )
        tools.extend([create_index, drop_index, execute_vacuum, kill_session, trigger_backup])
    except Exception as e:
        logger.warning(f"Action tools unavailable: {e}")

    try:
        from src.tools.gamification_tools import (
            get_active_quests,
            get_database_health_score,
            get_leaderboard,
            get_user_profile,
        )
        tools.extend([get_user_profile, get_leaderboard, get_active_quests, get_database_health_score])
    except Exception as e:
        logger.warning(f"Gamification tools unavailable: {e}")

    return tools


def create_agent(user_id: str, session_id: str) -> Agent:
    """Create and configure the DB Ops agent for a user session.

    Args:
        user_id: The authenticated user identifier. Accepted so a caller can
            attribute this session's actions, but deliberately **not** written to
            this module's logger — see the comment beside the ``logger.info``
            call below. Route it to the audit trail (``AuditHook``) instead,
            which is the surface intended to hold user-identifying data.
        session_id: The AgentCore Runtime session identifier. Opaque, and safe
            to log; it is what correlates an operational line with an audit
            record.

    Returns:
        A fully configured Strands Agent instance.
    """
    model = BedrockModel(
        model_id=settings.model_id,
        region_name=settings.aws_region,
    )

    tools = _load_tools()

    agent = Agent(
        model=model,
        tools=tools,
        system_prompt=DBOPS_SYSTEM_PROMPT,
    )

    # Operational metadata only. `user_id` is deliberately omitted: it is an
    # authenticated end-user identifier, and inlining it here would put it into
    # whatever general-purpose sink this logger writes to (CloudWatch Logs and
    # similar), where it cannot be given retention or access controls separate
    # from ordinary operational lines. Attribution of user actions belongs in the
    # audit trail written by AuditHook, which is scoped and retained for that
    # purpose. `session_id` is kept because it is an opaque per-conversation
    # identifier and is what correlates these lines with an audit record.
    logger.info(
        "Agent created: session=%s, model=%s, tools=%d",
        session_id,
        settings.model_id,
        len(tools),
    )

    return agent
