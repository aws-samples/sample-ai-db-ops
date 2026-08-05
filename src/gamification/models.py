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

"""Gamification data models."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Level(str, Enum):
    """User progression levels."""

    INTERN = "Intern"
    JUNIOR_DBA = "Junior DBA"
    DBA = "DBA"
    SENIOR_DBA = "Senior DBA"
    DB_ARCHITECT = "DB Architect"
    DB_LEGEND = "DB Legend"


# XP thresholds for each level
LEVEL_THRESHOLDS: dict[Level, int] = {
    Level.INTERN: 0,
    Level.JUNIOR_DBA: 500,
    Level.DBA: 1500,
    Level.SENIOR_DBA: 3500,
    Level.DB_ARCHITECT: 7000,
    Level.DB_LEGEND: 15000,
}


def get_level_for_xp(total_xp: int) -> Level:
    """Determine the level for a given XP total."""
    current_level = Level.INTERN
    for level, threshold in LEVEL_THRESHOLDS.items():
        if total_xp >= threshold:
            current_level = level
    return current_level


def get_xp_to_next_level(total_xp: int) -> int:
    """Calculate XP remaining to reach the next level."""
    levels = list(LEVEL_THRESHOLDS.items())
    for i, (level, threshold) in enumerate(levels):
        if total_xp < threshold:
            return threshold - total_xp
    return 0  # Already at max level


class Achievement(BaseModel):
    """A badge/achievement definition."""

    id: str
    name: str
    emoji: str
    description: str
    criteria: str


class Quest(BaseModel):
    """A quest/mission definition."""

    id: str
    name: str
    description: str
    xp_reward: int
    target_count: int
    quest_type: str  # daily, weekly, one-time


class UserProfile(BaseModel):
    """A user's gamification profile."""

    user_id: str
    display_name: str
    total_xp: int = 0
    level: Level = Level.INTERN
    level_name: str = "Intern"
    xp_to_next_level: int = 500
    badges: list[str] = []
    current_streak: int = 0
    longest_streak: int = 0
    team: Optional[str] = None
    weekly_xp: int = 0
    monthly_xp: int = 0
    operations_count: int = 0
    databases_managed: list[str] = []


class QuestProgress(BaseModel):
    """Tracks a user's progress on a quest."""

    quest_id: str
    user_id: str
    current_count: int = 0
    target_count: int = 1
    completed: bool = False
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# Achievement definitions
ACHIEVEMENTS: list[Achievement] = [
    Achievement(
        id="first_blood",
        name="First Blood",
        emoji="🔍",
        description="Complete first performance diagnosis",
        criteria="Execute get_slow_queries for the first time",
    ),
    Achievement(
        id="healer",
        name="Healer",
        emoji="🏥",
        description="Resolve a blocking session that lasted > 5 minutes",
        criteria="Kill a session with duration > 300 seconds",
    ),
    Achievement(
        id="speed_demon",
        name="Speed Demon",
        emoji="⚡",
        description="Optimize a query that improved by > 50%",
        criteria="Create an index that reduces query time by > 50%",
    ),
    Achievement(
        id="janitor",
        name="Janitor",
        emoji="🧹",
        description="Remove 5+ unused indexes",
        criteria="Drop 5 or more unused indexes",
    ),
    Achievement(
        id="oracle",
        name="Oracle",
        emoji="🔮",
        description="Predict a capacity issue before it triggered an alarm",
        criteria="Run capacity check when no active alarms exist",
    ),
    Achievement(
        id="guardian",
        name="Guardian",
        emoji="🛡️",
        description="Prevent a potential outage (detected before impact)",
        criteria="Identify and resolve a critical issue proactively",
    ),
    Achievement(
        id="sniper",
        name="Sniper",
        emoji="🎯",
        description="Fix an issue in a single agent interaction",
        criteria="Diagnose and resolve in one session with < 5 steps",
    ),
    Achievement(
        id="polyglot",
        name="Polyglot",
        emoji="🌍",
        description="Operate on 3+ different database engines in one session",
        criteria="Use tools on 3+ distinct engine types in a single session",
    ),
    Achievement(
        id="streak_master",
        name="Streak Master",
        emoji="🔥",
        description="Perform health checks 5 days in a row",
        criteria="Maintain a 5-day consecutive check streak",
    ),
    Achievement(
        id="zero_downtime",
        name="Zero Downtime",
        emoji="🏆",
        description="Maintain 30-day streak with no critical incidents",
        criteria="30 consecutive days without severity-1 incidents",
    ),
    Achievement(
        id="wizard",
        name="Wizard",
        emoji="🧙",
        description="Complete all achievements for a single engine",
        criteria="Earn all engine-specific badges for one engine type",
    ),
]

# Quest definitions
QUESTS: list[Quest] = [
    Quest(
        id="daily_health_check",
        name="Daily Health Check",
        description="Run performance check on all assigned databases",
        xp_reward=50,
        target_count=5,
        quest_type="daily",
    ),
    Quest(
        id="index_audit",
        name="Index Audit",
        description="Review and resolve all missing index recommendations",
        xp_reward=200,
        target_count=3,
        quest_type="weekly",
    ),
    Quest(
        id="capacity_forecast",
        name="Capacity Forecast",
        description="Generate capacity report for all P0 databases",
        xp_reward=150,
        target_count=3,
        quest_type="weekly",
    ),
    Quest(
        id="dead_weight",
        name="Dead Weight",
        description="Identify and remove all unused indexes in a database",
        xp_reward=300,
        target_count=5,
        quest_type="one-time",
    ),
    Quest(
        id="bloat_buster",
        name="Bloat Buster",
        description="Resolve table bloat across assigned PostgreSQL databases",
        xp_reward=250,
        target_count=2,
        quest_type="weekly",
    ),
    Quest(
        id="incident_responder",
        name="Incident Responder",
        description="Diagnose and resolve a blocking chain in < 5 minutes",
        xp_reward=500,
        target_count=1,
        quest_type="one-time",
    ),
]
