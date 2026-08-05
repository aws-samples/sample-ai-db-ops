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

"""Create DynamoDB tables for the DB Ops agent.

Run this script once to set up the required tables:
  python -m infra.dynamodb_tables
"""

import boto3

from src.config import settings


def create_tables():
    """Create all required DynamoDB tables."""
    dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)

    tables = [
        {
            "TableName": settings.registry_table,
            "KeySchema": [
                {"AttributeName": "db_identifier", "KeyType": "HASH"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "db_identifier", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": settings.gamification_table,
            "KeySchema": [
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": settings.leaderboard_table,
            "KeySchema": [
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
    ]

    for table_def in tables:
        table_name = table_def["TableName"]
        try:
            dynamodb.create_table(**table_def)
            print(f"✓ Created table: {table_name}")
        except dynamodb.exceptions.ResourceInUseException:
            print(f"• Table already exists: {table_name}")
        except Exception as e:
            print(f"✗ Failed to create {table_name}: {e}")


def seed_sample_registry():
    """Seed the registry with sample database entries for testing."""
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    table = dynamodb.Table(settings.registry_table)

    sample_databases = [
        {
            "db_identifier": "prod-orders-pg",
            "engine": "aurora-postgresql",
            "engine_version": "15.4",
            "endpoint": "prod-orders.cluster-xxx.us-east-1.rds.amazonaws.com",
            "port": 5432,
            "secret_arn": "arn:aws:secretsmanager:us-east-1:123456789:secret:prod-orders-readonly",
            "privileged_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789:secret:prod-orders-admin",
            "environment": "production",
            "team_owner": "orders-team",
            "tier_3_approvers": ["dba-team", "orders-lead"],
            "tags": ["critical", "pci"],
            "health_score": 87,
            "last_checked": "2026-05-11T08:30:00Z",
        },
        {
            "db_identifier": "prod-sessions-redis",
            "engine": "elasticache-redis",
            "engine_version": "7.0",
            "endpoint": "prod-sessions.xxx.use1.cache.amazonaws.com",
            "port": 6379,
            "secret_arn": "arn:aws:secretsmanager:us-east-1:123456789:secret:prod-sessions-redis",
            "environment": "production",
            "team_owner": "platform-team",
            "tier_3_approvers": ["platform-lead"],
            "tags": ["critical"],
            "health_score": 92,
            "last_checked": "2026-05-11T09:00:00Z",
        },
        {
            "db_identifier": "prod-events-mysql",
            "engine": "aurora-mysql",
            "engine_version": "8.0",
            "endpoint": "prod-events.cluster-xxx.us-east-1.rds.amazonaws.com",
            "port": 3306,
            "secret_arn": "arn:aws:secretsmanager:us-east-1:123456789:secret:prod-events-readonly",
            "privileged_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789:secret:prod-events-admin",
            "environment": "production",
            "team_owner": "events-team",
            "tier_3_approvers": ["dba-team"],
            "tags": [],
            "health_score": 74,
            "last_checked": "2026-05-10T18:00:00Z",
        },
        {
            "db_identifier": "dev-orders-pg",
            "engine": "rds-postgresql",
            "engine_version": "15.4",
            "endpoint": "dev-orders.xxx.us-east-1.rds.amazonaws.com",
            "port": 5432,
            "secret_arn": "arn:aws:secretsmanager:us-east-1:123456789:secret:dev-orders-creds",
            "privileged_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789:secret:dev-orders-creds",
            "environment": "development",
            "team_owner": "orders-team",
            "tier_3_approvers": [],
            "tags": ["dev"],
            "health_score": 95,
            "last_checked": "2026-05-11T09:15:00Z",
        },
    ]

    for db in sample_databases:
        table.put_item(Item=db)
        print(f"✓ Seeded: {db['db_identifier']}")


if __name__ == "__main__":
    print("Creating DynamoDB tables...")
    create_tables()
    print("\nSeeding sample registry data...")
    seed_sample_registry()
    print("\nDone!")
