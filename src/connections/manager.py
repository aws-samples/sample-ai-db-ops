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

"""Connection manager — retrieves credentials from Secrets Manager and creates DB connections."""

import json
import logging
from typing import Any

import boto3

from src.admin_ops.db.tls import (
    mysql_ssl_kwargs,
    postgres_ssl_kwargs,
    redis_ssl_kwargs,
)
from src.config import settings
from src.registry.models import DatabaseEngine, DatabaseEntry

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages database connections using credentials from AWS Secrets Manager."""

    def __init__(self):
        self._secrets_client = boto3.client(
            "secretsmanager", region_name=settings.aws_region
        )
        self._connections: dict[str, Any] = {}

    def _get_secret(self, secret_arn: str) -> dict:
        """Retrieve and parse a secret from Secrets Manager."""
        response = self._secrets_client.get_secret_value(SecretId=secret_arn)
        return json.loads(response["SecretString"])

    def get_readonly_connection(self, db_entry: DatabaseEntry) -> Any:
        """Get a read-only connection for Tier 1/2 operations."""
        cache_key = f"ro_{db_entry.db_identifier}"
        if cache_key in self._connections:
            conn = self._connections[cache_key]
            if self._is_alive(conn, db_entry.engine):
                return conn

        creds = self._get_secret(db_entry.secret_arn)
        conn = self._create_connection(db_entry, creds)
        self._connections[cache_key] = conn
        return conn

    def get_privileged_connection(self, db_entry: DatabaseEntry) -> Any:
        """Get a privileged connection for Tier 3 operations. Requires approval."""
        if not db_entry.privileged_secret_arn:
            raise PermissionError(
                f"No privileged credentials configured for {db_entry.db_identifier}"
            )

        cache_key = f"priv_{db_entry.db_identifier}"
        if cache_key in self._connections:
            conn = self._connections[cache_key]
            if self._is_alive(conn, db_entry.engine):
                return conn

        creds = self._get_secret(db_entry.privileged_secret_arn)
        conn = self._create_connection(db_entry, creds)
        self._connections[cache_key] = conn
        return conn

    def _create_connection(self, db_entry: DatabaseEntry, creds: dict) -> Any:
        """Create a database connection based on engine type."""
        engine = db_entry.engine

        if engine in (
            DatabaseEngine.AURORA_POSTGRESQL,
            DatabaseEngine.RDS_POSTGRESQL,
        ):
            try:
                import psycopg2
            except ImportError:
                raise RuntimeError(
                    "psycopg2 not installed. Cannot connect to PostgreSQL."
                )

            conn = psycopg2.connect(
                host=db_entry.endpoint,
                port=db_entry.port,
                user=creds["username"],
                password=creds["password"],
                dbname=creds.get("dbname", "postgres"),
                options=f"-c statement_timeout={settings.statement_timeout_seconds * 1000}",
                # Encryption in transit; see src/admin_ops/db/tls.py.
                **postgres_ssl_kwargs(db_entry.endpoint),
            )
            conn.autocommit = True
            return conn

        elif engine in (
            DatabaseEngine.AURORA_MYSQL,
            DatabaseEngine.RDS_MYSQL,
        ):
            try:
                import pymysql
            except ImportError:
                raise RuntimeError(
                    "pymysql not installed. Cannot connect to MySQL."
                )

            return pymysql.connect(
                host=db_entry.endpoint,
                port=db_entry.port,
                user=creds["username"],
                password=creds["password"],
                database=creds.get("dbname", "mysql"),
                read_timeout=settings.statement_timeout_seconds,
                cursorclass=pymysql.cursors.DictCursor,
                # Encryption in transit; see src/admin_ops/db/tls.py.
                **mysql_ssl_kwargs(db_entry.endpoint),
            )

        elif engine == DatabaseEngine.ELASTICACHE_REDIS:
            try:
                import redis
            except ImportError:
                raise RuntimeError(
                    "redis not installed. Cannot connect to ElastiCache."
                )

            return redis.Redis(
                host=db_entry.endpoint,
                port=db_entry.port,
                password=creds.get("password"),
                decode_responses=True,
                socket_timeout=settings.statement_timeout_seconds,
                # Encryption in transit; see src/admin_ops/db/tls.py. Redis AUTH
                # sends the password as a cleartext command argument, so this is
                # protecting the credential as well as the data.
                **redis_ssl_kwargs(db_entry.endpoint),
            )

        else:
            raise NotImplementedError(f"Engine {engine} connection not yet implemented")

    def _is_alive(self, conn: Any, engine: DatabaseEngine) -> bool:
        """Check if a connection is still alive."""
        try:
            if engine in (
                DatabaseEngine.AURORA_POSTGRESQL,
                DatabaseEngine.RDS_POSTGRESQL,
            ):
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return True
            elif engine in (
                DatabaseEngine.AURORA_MYSQL,
                DatabaseEngine.RDS_MYSQL,
            ):
                conn.ping(reconnect=False)
                return True
            elif engine == DatabaseEngine.ELASTICACHE_REDIS:
                return conn.ping()
        except Exception:
            return False
        return False

    def close_all(self) -> None:
        """Close all cached connections."""
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()
