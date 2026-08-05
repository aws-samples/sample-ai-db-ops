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

"""Data models for the database registry."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class DatabaseEngine(str, Enum):
    """Supported database engines."""

    AURORA_POSTGRESQL = "aurora-postgresql"
    AURORA_MYSQL = "aurora-mysql"
    RDS_POSTGRESQL = "rds-postgresql"
    RDS_MYSQL = "rds-mysql"
    RDS_SQLSERVER = "rds-sqlserver"
    DYNAMODB = "dynamodb"
    REDSHIFT = "redshift"
    ELASTICACHE_REDIS = "elasticache-redis"
    DOCUMENTDB = "documentdb"


class Environment(str, Enum):
    """Deployment environments."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class DatabaseEntry(BaseModel):
    """A database instance in the fleet registry."""

    db_identifier: str
    engine: DatabaseEngine
    engine_version: str
    endpoint: str
    port: int
    secret_arn: str
    privileged_secret_arn: Optional[str] = None
    environment: Environment = Environment.PRODUCTION
    team_owner: str
    tier_3_approvers: list[str] = []
    tags: list[str] = []
    health_score: int = 100
    last_checked: Optional[str] = None
