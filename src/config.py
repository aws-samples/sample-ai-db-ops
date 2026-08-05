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

"""Application configuration using Pydantic settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global application settings loaded from environment variables."""

    # AWS
    aws_region: str = "us-east-1"

    # Bedrock Model
    model_id: str = "us.anthropic.claude-sonnet-4-6-v1"

    # DynamoDB Tables
    registry_table: str = "dbops-registry"
    gamification_table: str = "dbops-gamification"
    leaderboard_table: str = "dbops-leaderboard"

    # Agent
    conversation_window_size: int = 50
    statement_timeout_seconds: int = 30
    tier3_approval_timeout_minutes: int = 30

    # Gamification
    xp_tier1: int = 10
    xp_tier2: int = 25
    xp_tier3: int = 50
    proactive_bonus_multiplier: int = 2

    model_config = {"env_prefix": "DBOPS_"}


settings = Settings()
