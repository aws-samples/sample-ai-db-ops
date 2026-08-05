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

"""Gamification tools — exposed to the agent for user queries about progress."""

from strands import tool

from src.gamification.engine import GamificationEngine


@tool
def get_user_profile(user_id: str) -> dict:
    """Get the gamification profile for a user including XP, level, badges, and streak.

    Args:
        user_id: The user identifier.

    Returns:
        A dict with the user's full gamification profile.
    """
    engine = GamificationEngine()
    profile = engine.get_profile(user_id)
    return profile.model_dump()


@tool
def get_leaderboard(period: str = "weekly", limit: int = 10) -> dict:
    """Get the XP leaderboard for the specified time period.

    Args:
        period: Time period — 'weekly' or 'monthly'.
        limit: Number of entries to return (default 10).

    Returns:
        A dict with ranked leaderboard entries.
    """
    engine = GamificationEngine()
    entries = engine.get_leaderboard(period=period, limit=limit)

    ranked = []
    for i, entry in enumerate(entries, 1):
        ranked.append({
            "rank": i,
            "user_id": entry.get("user_id"),
            "weekly_xp": entry.get("weekly_xp", 0),
            "total_xp": entry.get("total_xp", 0),
        })

    return {
        "period": period,
        "leaderboard": ranked,
        "total_entries": len(ranked),
    }


@tool
def get_active_quests(user_id: str) -> dict:
    """Get active quests and their progress for a user.

    Args:
        user_id: The user identifier.

    Returns:
        A dict with active quests, progress, and available XP rewards.
    """
    engine = GamificationEngine()
    quests = engine.get_active_quests(user_id)

    active = [q for q in quests if not q["completed"]]
    completed = [q for q in quests if q["completed"]]

    return {
        "user_id": user_id,
        "active_quests": active,
        "completed_quests": completed,
        "total_available_xp": sum(q["xp_reward"] for q in active),
    }


@tool
def get_database_health_score(db_identifier: str) -> dict:
    """Get the health score and status for a specific database.

    Args:
        db_identifier: The database identifier from the fleet registry.

    Returns:
        A dict with the health score, status indicator, and contributing factors.
    """
    from src.registry.repository import DatabaseRegistry

    registry = DatabaseRegistry()
    entry = registry.get(db_identifier)

    if entry is None:
        return {"error": f"Database '{db_identifier}' not found in registry."}

    score = entry.health_score
    if score >= 80:
        status = "🟢 OK"
    elif score >= 60:
        status = "🟡 WARN"
    else:
        status = "🔴 CRITICAL"

    return {
        "db_identifier": db_identifier,
        "health_score": score,
        "status": status,
        "last_checked": entry.last_checked,
        "team_owner": entry.team_owner,
        "environment": entry.environment.value,
    }
