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

"""Seed Aurora MySQL for the demo by driving the agent (which is in the VPC).

Uses the MySQL agent's execute_sql tool to create schemas and bulk-insert
realistic data. Reads the agent ARN from ui/.env.local. Idempotent — safe
to re-run; CREATE TABLE IF NOT EXISTS + counts make duplicate runs visible.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import boto3

REGION = os.environ.get("AGENT_REGION", "us-east-1")
ENV_FILE = Path(__file__).resolve().parent.parent / "ui" / ".env.local"


def read_arn() -> str:
    """Pull MYSQL_AGENT_ARN out of ui/.env.local without dotenv."""
    if not ENV_FILE.exists():
        sys.exit(f"missing {ENV_FILE}")
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r"^\s*MYSQL_AGENT_ARN\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    sys.exit("MYSQL_AGENT_ARN not found in ui/.env.local")


client = boto3.client("bedrock-agentcore", region_name=REGION)
ARN = read_arn()


def call(prompt: str, session: str) -> str:
    payload = json.dumps({"prompt": prompt, "user_id": "dbops-user"})
    sid = (session + "-padded-padded-padded-padded-padded")[:48]
    r = client.invoke_agent_runtime(
        agentRuntimeArn=ARN,
        qualifier="DEFAULT",
        runtimeSessionId=sid,
        payload=payload,
    )
    return r["response"].read().decode()[:3000]


def summarise(response: str) -> str:
    """Return metadata about an agent response instead of the response itself.

    The body echoes whatever the agent retrieved, and these prompts touch the
    ``users``, ``subscriptions`` and ``events`` tables — so in a real deployment
    it can carry row data into a terminal, a CI log, or a pasted transcript.
    Printing a summary keeps the script usable for confirming a seed ran without
    making the data the default output.

    Set ``SEED_VERBOSE=1`` to print the full body when debugging locally.
    """
    if os.environ.get("SEED_VERBOSE") == "1":
        return response
    first = response.strip().splitlines()[0][:120] if response.strip() else "(empty)"
    return (
        f"agent replied: {len(response)} chars; first line: {first!r} "
        "(set SEED_VERBOSE=1 to print the full body)"
    )


# ─── 1. Schema ────────────────────────────────────────────────────────────
SCHEMA = """Use the execute_sql tool to run each statement. Just run them,
no commentary needed.

USE appdb;

CREATE TABLE IF NOT EXISTS users (
    user_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
    email      VARCHAR(255),
    full_name  VARCHAR(255),
    plan       VARCHAR(32),
    last_login DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    sub_id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id             BIGINT,
    plan                VARCHAR(32),
    status              VARCHAR(32),
    monthly_price_cents INT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    event_id   BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id    BIGINT,
    event_type VARCHAR(64),
    payload    JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

SELECT 'schema_ready' AS status, COUNT(*) AS user_count FROM users;
"""

# ─── 2. Data ──────────────────────────────────────────────────────────────
# Multi-table cross-join generates 1500 users; each user gets a sub and ~10
# events. Tame numbers so it lands fast; the demo doesn't need millions.
DATA = """Use the execute_sql tool to run each of these statements in
sequence. Just run them, no commentary.

USE appdb;

INSERT INTO users (email, full_name, plan)
SELECT CONCAT('user', t.n, '@example.com'),
       CONCAT('User ', t.n),
       ELT(1+(t.n%3), 'free', 'pro', 'enterprise')
FROM (
    SELECT a.n + b.n*40 AS n
    FROM (SELECT 0 AS n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
          UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9
          UNION SELECT 10 UNION SELECT 11 UNION SELECT 12 UNION SELECT 13 UNION SELECT 14
          UNION SELECT 15 UNION SELECT 16 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19
          UNION SELECT 20 UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24
          UNION SELECT 25 UNION SELECT 26 UNION SELECT 27 UNION SELECT 28 UNION SELECT 29
          UNION SELECT 30 UNION SELECT 31 UNION SELECT 32 UNION SELECT 33 UNION SELECT 34
          UNION SELECT 35 UNION SELECT 36 UNION SELECT 37 UNION SELECT 38 UNION SELECT 39) a,
         (SELECT 0 AS n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
          UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9
          UNION SELECT 10 UNION SELECT 11 UNION SELECT 12 UNION SELECT 13 UNION SELECT 14
          UNION SELECT 15 UNION SELECT 16 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19
          UNION SELECT 20 UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24
          UNION SELECT 25 UNION SELECT 26 UNION SELECT 27 UNION SELECT 28 UNION SELECT 29
          UNION SELECT 30 UNION SELECT 31 UNION SELECT 32 UNION SELECT 33 UNION SELECT 34
          UNION SELECT 35 UNION SELECT 36 UNION SELECT 37) b
    WHERE (a.n + b.n*40) < 1500
) t;

INSERT INTO subscriptions (user_id, plan, status, monthly_price_cents)
SELECT user_id, plan,
       ELT(1+(user_id%3),'active','trial','cancelled'),
       CASE plan WHEN 'pro' THEN 1900 WHEN 'enterprise' THEN 9900 ELSE 0 END
FROM users
WHERE NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.user_id = users.user_id);

INSERT INTO events (user_id, event_type, payload)
SELECT u.user_id,
       ELT(1+(u.user_id*7%5), 'login','page_view','click','purchase','error'),
       JSON_OBJECT('path', CONCAT('/page/', u.user_id%50))
FROM users u
JOIN (SELECT 0 AS r UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
      UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) r;

SELECT 'users' AS table_name, COUNT(*) AS row_count FROM users
UNION ALL SELECT 'subscriptions', COUNT(*) FROM subscriptions
UNION ALL SELECT 'events', COUNT(*) FROM events;
"""

print("=== Step 1: schema ===")
print(summarise(call(SCHEMA, "seed-mysql-schema")))

print("\n=== Step 2: data ===")
print(summarise(call(DATA, "seed-mysql-data")))
