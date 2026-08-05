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

"""Gamification hook — awards XP and checks achievements after each operation."""

import logging
from typing import Any

from src.config import settings
from src.gamification.engine import GamificationEngine
from src.tools._helpers import get_tool_tier

logger = logging.getLogger(__name__)


class GamificationHook:
    """Award XP and check achievements after each tool execution.

    XP scales by tier:
    - Tier 1 (read-only): 10 XP
    - Tier 2 (advisory): 25 XP
    - Tier 3 (actioned): 50 XP

    Bonus: 2x XP for proactive checks (no active alarm on the database).
    """

    def __init__(self):
        self._engine = GamificationEngine()
        self._user_id: str | None = None
        self._session_engines: set[str] = set()  # Track engines used in session

    def set_user(self, user_id: str) -> None:
        """Set the current user for XP attribution."""
        self._user_id = user_id

    def after_tool_call(
        self,
        tool_name: str,
        tool_input: dict,
        tool_output: Any,
        **kwargs: Any,
    ) -> dict | None:
        """Called after every tool execution — awards XP and checks achievements.

        Returns:
            A dict with gamification results (XP earned, badges, quests) or None.
        """
        if not self._user_id:
            return None

        # Skip gamification tools themselves to avoid infinite loops
        gamification_tools = {
            "get_user_profile",
            "get_leaderboard",
            "get_active_quests",
            "get_database_health_score",
        }
        if tool_name in gamification_tools:
            return None

        # Skip if tool errored
        if isinstance(tool_output, dict) and "error" in tool_output:
            return None

        tier = get_tool_tier(tool_name)
        xp_base = {1: settings.xp_tier1, 2: settings.xp_tier2, 3: settings.xp_tier3}.get(
            tier, 5
        )

        # Bonus XP for proactive checks
        db_identifier = tool_input.get("db_identifier")
        if self._is_proactive_check(tool_name, db_identifier):
            xp_base *= settings.proactive_bonus_multiplier

        # Award XP
        xp_result = self._engine.award_xp(
            user_id=self._user_id,
            xp_amount=xp_base,
            reason=f"Executed {tool_name}",
            tool_name=tool_name,
        )

        # Check achievements
        new_badges = self._engine.check_achievements(
            user_id=self._user_id,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output if isinstance(tool_output, dict) else {},
        )

        # Update quest progress
        completed_quests = []
        if db_identifier:
            completed_quests = self._engine.update_quest_progress(
                user_id=self._user_id,
                tool_name=tool_name,
                db_identifier=db_identifier,
            )

        # Track engines for polyglot achievement
        if db_identifier:
            from src.tools._helpers import get_registry
            registry = get_registry()
            entry = registry.get(db_identifier)
            if entry:
                self._session_engines.add(entry.engine.value)

        # Update health score
        if db_identifier:
            self._engine.update_health_score(db_identifier, tool_name)

        # Update streak (once per day)
        self._engine.update_streak(self._user_id)

        result = {
            "xp_earned": xp_result["xp_earned"],
            "total_xp": xp_result["total_xp"],
            "level": xp_result["level"],
        }

        if xp_result.get("level_up"):
            result["level_up"] = True
            result["message"] = f"🎉 Level up! You are now: {xp_result['level']}"

        if new_badges:
            result["new_badges"] = new_badges
            result["badge_message"] = f"🏅 Achievement unlocked: {', '.join(new_badges)}!"

        if completed_quests:
            result["completed_quests"] = completed_quests
            result["quest_message"] = f"📋 Quest completed: {', '.join(completed_quests)}!"

        return result

    def _is_proactive_check(self, tool_name: str, db_identifier: str | None) -> bool:
        """Determine if this is a proactive check (no active alarm).

        Proactive checks earn bonus XP because they prevent incidents.
        """
        proactive_tools = {
            "get_slow_queries",
            "get_vacuum_status",
            "get_missing_indexes",
            "get_table_bloat",
            "get_cloudwatch_metrics",
            "get_index_usage",
            "get_backup_status",
        }

        if tool_name not in proactive_tools:
            return False

        # In a full implementation, check CloudWatch Alarms for this database
        # If no active alarms → proactive (bonus XP)
        # For now, assume proactive if health score > 70
        if db_identifier:
            from src.tools._helpers import get_registry
            registry = get_registry()
            entry = registry.get(db_identifier)
            if entry and entry.health_score > 70:
                return True

        return False
