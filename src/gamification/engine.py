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

"""Gamification engine — manages XP, levels, achievements, and leaderboards."""

from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from src.config import settings
from src.gamification.models import (
    ACHIEVEMENTS,
    QUESTS,
    Level,
    QuestProgress,
    UserProfile,
    get_level_for_xp,
    get_xp_to_next_level,
)


class GamificationEngine:
    """Core gamification logic — XP awards, achievement checks, leaderboard updates."""

    def __init__(self):
        self._dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self._table = self._dynamodb.Table(settings.gamification_table)
        self._leaderboard_table = self._dynamodb.Table(settings.leaderboard_table)

    # ─── User Profile ───────────────────────────────────────────────────────

    def get_profile(self, user_id: str) -> UserProfile:
        """Get or create a user's gamification profile."""
        try:
            response = self._table.get_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE"})
            item = response.get("Item")
            if item:
                return UserProfile(**item.get("data", {}))
        except ClientError:
            pass

        # Create new profile
        profile = UserProfile(user_id=user_id, display_name=user_id)
        self._save_profile(profile)
        return profile

    def _save_profile(self, profile: UserProfile) -> None:
        """Persist a user profile to DynamoDB."""
        self._table.put_item(
            Item={
                "pk": f"USER#{profile.user_id}",
                "sk": "PROFILE",
                "data": profile.model_dump(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    # ─── XP Management ──────────────────────────────────────────────────────

    def award_xp(
        self, user_id: str, xp_amount: int, reason: str, tool_name: Optional[str] = None
    ) -> dict:
        """Award XP to a user and check for level-ups.

        Returns:
            A dict with xp_earned, new_total, level_up info, and any new badges.
        """
        profile = self.get_profile(user_id)
        old_level = profile.level

        profile.total_xp += xp_amount
        profile.weekly_xp += xp_amount
        profile.monthly_xp += xp_amount
        profile.operations_count += 1

        # Recalculate level
        new_level = get_level_for_xp(profile.total_xp)
        profile.level = new_level
        profile.level_name = new_level.value
        profile.xp_to_next_level = get_xp_to_next_level(profile.total_xp)

        level_up = old_level != new_level

        self._save_profile(profile)
        self._update_leaderboard(user_id, profile.total_xp, profile.weekly_xp)

        # Log XP event
        self._log_xp_event(user_id, xp_amount, reason, tool_name)

        return {
            "xp_earned": xp_amount,
            "total_xp": profile.total_xp,
            "level": new_level.value,
            "level_up": level_up,
            "xp_to_next_level": profile.xp_to_next_level,
        }

    def _log_xp_event(
        self, user_id: str, xp: int, reason: str, tool_name: Optional[str]
    ) -> None:
        """Log an XP award event for audit trail."""
        ts = datetime.now(timezone.utc).isoformat()
        self._table.put_item(
            Item={
                "pk": f"USER#{user_id}",
                "sk": f"XP#{ts}",
                "xp": xp,
                "reason": reason,
                "tool_name": tool_name or "unknown",
                "timestamp": ts,
            }
        )

    # ─── Achievements ───────────────────────────────────────────────────────

    def check_achievements(
        self, user_id: str, tool_name: str, tool_input: dict, tool_output: dict
    ) -> list[str]:
        """Check if any new achievements were unlocked by this action.

        Returns:
            List of newly unlocked achievement names (with emoji).
        """
        profile = self.get_profile(user_id)
        new_badges = []

        for achievement in ACHIEVEMENTS:
            if achievement.id in profile.badges:
                continue  # Already earned

            unlocked = self._evaluate_achievement(
                achievement.id, profile, tool_name, tool_input, tool_output
            )
            if unlocked:
                profile.badges.append(achievement.id)
                new_badges.append(f"{achievement.emoji} {achievement.name}")

        if new_badges:
            self._save_profile(profile)

        return new_badges

    def _evaluate_achievement(
        self,
        achievement_id: str,
        profile: UserProfile,
        tool_name: str,
        tool_input: dict,
        tool_output: dict,
    ) -> bool:
        """Evaluate whether a specific achievement criteria is met."""
        if achievement_id == "first_blood":
            return tool_name == "get_slow_queries"

        elif achievement_id == "healer":
            if tool_name == "kill_session":
                return tool_output.get("success", False)
            return False

        elif achievement_id == "janitor":
            if tool_name == "drop_index":
                # Count total dropped indexes
                return profile.operations_count >= 5  # Simplified check
            return False

        elif achievement_id == "streak_master":
            return profile.current_streak >= 5

        elif achievement_id == "zero_downtime":
            return profile.current_streak >= 30

        return False

    # ─── Streak Management ──────────────────────────────────────────────────

    def update_streak(self, user_id: str) -> int:
        """Update the user's daily streak. Call once per day on first interaction.

        Returns:
            The current streak count.
        """
        profile = self.get_profile(user_id)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Check last activity date
        last_key = f"USER#{user_id}"
        try:
            response = self._table.get_item(
                Key={"pk": last_key, "sk": "LAST_ACTIVE"}
            )
            last_active = response.get("Item", {}).get("date")
        except ClientError:
            last_active = None

        if last_active == today:
            return profile.current_streak  # Already counted today

        from datetime import timedelta

        yesterday = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%d")

        if last_active == yesterday:
            profile.current_streak += 1
        else:
            profile.current_streak = 1  # Reset streak

        if profile.current_streak > profile.longest_streak:
            profile.longest_streak = profile.current_streak

        # Update last active
        self._table.put_item(
            Item={"pk": last_key, "sk": "LAST_ACTIVE", "date": today}
        )
        self._save_profile(profile)
        return profile.current_streak

    # ─── Leaderboard ────────────────────────────────────────────────────────

    def _update_leaderboard(self, user_id: str, total_xp: int, weekly_xp: int) -> None:
        """Update the leaderboard entry for a user."""
        self._leaderboard_table.put_item(
            Item={
                "pk": "WEEKLY",
                "sk": f"USER#{user_id}",
                "user_id": user_id,
                "total_xp": total_xp,
                "weekly_xp": weekly_xp,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def get_leaderboard(self, period: str = "weekly", limit: int = 10) -> list[dict]:
        """Get the leaderboard for a given period.

        Args:
            period: 'weekly' or 'monthly'.
            limit: Number of entries to return.

        Returns:
            Sorted list of leaderboard entries.
        """
        pk = period.upper()
        try:
            response = self._leaderboard_table.query(
                KeyConditionExpression="pk = :pk",
                ExpressionAttributeValues={":pk": pk},
                Limit=limit,
                ScanIndexForward=False,
            )
            items = response.get("Items", [])
            # Sort by weekly_xp descending
            items.sort(key=lambda x: x.get("weekly_xp", 0), reverse=True)
            return items[:limit]
        except ClientError:
            return []

    # ─── Quest Progress ─────────────────────────────────────────────────────

    def get_active_quests(self, user_id: str) -> list[dict]:
        """Get active quests and their progress for a user."""
        quests_with_progress = []
        for quest in QUESTS:
            progress = self._get_quest_progress(user_id, quest.id)
            quests_with_progress.append({
                "quest_id": quest.id,
                "name": quest.name,
                "description": quest.description,
                "xp_reward": quest.xp_reward,
                "progress": progress.current_count,
                "target": quest.target_count,
                "completed": progress.completed,
                "quest_type": quest.quest_type,
            })
        return quests_with_progress

    def _get_quest_progress(self, user_id: str, quest_id: str) -> QuestProgress:
        """Get progress for a specific quest."""
        try:
            response = self._table.get_item(
                Key={"pk": f"USER#{user_id}", "sk": f"QUEST#{quest_id}"}
            )
            item = response.get("Item")
            if item:
                return QuestProgress(**item.get("data", {}))
        except ClientError:
            pass

        quest = next((q for q in QUESTS if q.id == quest_id), None)
        return QuestProgress(
            quest_id=quest_id,
            user_id=user_id,
            target_count=quest.target_count if quest else 1,
        )

    def update_quest_progress(self, user_id: str, tool_name: str, db_identifier: str) -> list[str]:
        """Update quest progress based on the tool executed.

        Returns:
            List of completed quest names (if any completed this action).
        """
        completed_quests = []

        # Map tools to quests
        quest_tool_map = {
            "daily_health_check": ["get_slow_queries", "get_active_sessions", "get_cloudwatch_metrics"],
            "index_audit": ["get_missing_indexes", "get_index_usage"],
            "capacity_forecast": ["recommend_capacity_change", "get_cloudwatch_metrics"],
            "dead_weight": ["drop_index"],
            "bloat_buster": ["execute_vacuum", "get_table_bloat"],
            "incident_responder": ["kill_session"],
        }

        for quest_id, tools in quest_tool_map.items():
            if tool_name in tools:
                progress = self._get_quest_progress(user_id, quest_id)
                if not progress.completed:
                    progress.current_count += 1
                    quest = next((q for q in QUESTS if q.id == quest_id), None)
                    if quest and progress.current_count >= quest.target_count:
                        progress.completed = True
                        progress.completed_at = datetime.now(timezone.utc).isoformat()
                        completed_quests.append(quest.name)
                        # Award quest XP
                        self.award_xp(user_id, quest.xp_reward, f"Quest completed: {quest.name}")

                    # Save progress
                    self._table.put_item(
                        Item={
                            "pk": f"USER#{user_id}",
                            "sk": f"QUEST#{quest_id}",
                            "data": progress.model_dump(),
                        }
                    )

        return completed_quests

    # ─── Health Score ───────────────────────────────────────────────────────

    def update_health_score(self, db_identifier: str, tool_name: str) -> None:
        """Update the health score for a database based on the operation performed.

        Health score improves with proactive checks and degrades over time without them.
        """
        # Proactive tools improve health score
        health_boost_tools = {
            "get_slow_queries": 2,
            "get_vacuum_status": 3,
            "get_missing_indexes": 2,
            "get_table_bloat": 2,
            "execute_vacuum": 5,
            "create_index": 5,
            "get_cloudwatch_metrics": 1,
        }

        boost = health_boost_tools.get(tool_name, 0)
        if boost > 0 and db_identifier:
            from src.registry.repository import DatabaseRegistry

            registry = DatabaseRegistry()
            entry = registry.get(db_identifier)
            if entry:
                new_score = min(100, entry.health_score + boost)
                registry.update_health_score(db_identifier, new_score)
                registry.update_last_checked(
                    db_identifier, datetime.now(timezone.utc).isoformat()
                )
