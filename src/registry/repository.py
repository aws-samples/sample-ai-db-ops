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

"""DynamoDB-backed database registry repository."""

import boto3
from botocore.exceptions import ClientError

from src.config import settings
from src.registry.models import DatabaseEntry


class DatabaseRegistry:
    """Manages the fleet of monitored databases in DynamoDB."""

    def __init__(self):
        self._dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self._table = self._dynamodb.Table(settings.registry_table)

    def get(self, db_identifier: str) -> DatabaseEntry | None:
        """Retrieve a database entry by identifier."""
        try:
            response = self._table.get_item(Key={"db_identifier": db_identifier})
            item = response.get("Item")
            if item:
                return DatabaseEntry(**item)
            return None
        except ClientError:
            return None

    def list_all(self) -> list[DatabaseEntry]:
        """List all registered databases."""
        response = self._table.scan()
        items = response.get("Items", [])
        return [DatabaseEntry(**item) for item in items]

    def list_by_team(self, team_owner: str) -> list[DatabaseEntry]:
        """List databases owned by a specific team."""
        all_dbs = self.list_all()
        return [db for db in all_dbs if db.team_owner == team_owner]

    def register(self, entry: DatabaseEntry) -> None:
        """Register or update a database entry."""
        self._table.put_item(Item=entry.model_dump())

    def update_health_score(self, db_identifier: str, score: int) -> None:
        """Update the health score for a database."""
        self._table.update_item(
            Key={"db_identifier": db_identifier},
            UpdateExpression="SET health_score = :score",
            ExpressionAttributeValues={":score": score},
        )

    def update_last_checked(self, db_identifier: str, timestamp: str) -> None:
        """Update the last checked timestamp."""
        self._table.update_item(
            Key={"db_identifier": db_identifier},
            UpdateExpression="SET last_checked = :ts",
            ExpressionAttributeValues={":ts": timestamp},
        )
