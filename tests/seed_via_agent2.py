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

"""Round 2: bulk-insert MySQL data and run heavy queries on PG/MySQL."""
import os

import boto3, json

REGION = "us-east-1"
client = boto3.client("bedrock-agentcore", region_name=REGION)

PG_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/dbops_postgresql-XXXXXXXXXX"
MY_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/dbops_mysql-XXXXXXXXXX"
OR_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/dbops_oracle-XXXXXXXXXX"

def call(arn, prompt, sid):
    payload = json.dumps({"prompt": prompt, "user_id": "dbops-user"})
    sid_padded = (sid + "-padded-padded-padded-padded-padded")[:48]
    r = client.invoke_agent_runtime(
        agentRuntimeArn=arn, qualifier="DEFAULT",
        runtimeSessionId=sid_padded, payload=payload,
    )
    return r["response"].read().decode()[:2500]

def summarise(response):
    """Return metadata about an agent response instead of the response itself.

    The body echoes whatever the agent retrieved, and these prompts touch the
    ``users``, ``subscriptions`` and ``events`` tables — so in a real deployment
    it can carry row data (emails, plans, event payloads) into a terminal, a CI
    log, or a pasted transcript. Printing a summary keeps the script usable for
    confirming a seed ran without making the data the default output.

    Set ``SEED_VERBOSE=1`` to print the full body when debugging locally.
    """
    if os.environ.get("SEED_VERBOSE") == "1":
        return response
    first = response.strip().splitlines()[0][:120] if response.strip() else "(empty)"
    return (
        f"agent replied: {len(response)} chars; first line: {first!r} "
        "(set SEED_VERBOSE=1 to print the full body)"
    )


# MySQL: bulk-insert via INSERT ... SELECT FROM information_schema.columns recursion-style cross join
MY_LOAD = """Use the execute_sql tool to run these statements in order. Just execute, do not explain.

USE appdb;

INSERT INTO users (email, full_name, plan)
SELECT CONCAT('user', t.n, '@example.com'), CONCAT('User ', t.n),
       ELT(1+(t.n%3), 'free', 'pro', 'enterprise')
FROM (
    SELECT a.n + b.n*100 AS n
    FROM (SELECT 0 AS n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9
          UNION SELECT 10 UNION SELECT 11 UNION SELECT 12 UNION SELECT 13 UNION SELECT 14 UNION SELECT 15 UNION SELECT 16 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19
          UNION SELECT 20 UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24 UNION SELECT 25 UNION SELECT 26 UNION SELECT 27 UNION SELECT 28 UNION SELECT 29
          UNION SELECT 30 UNION SELECT 31 UNION SELECT 32 UNION SELECT 33 UNION SELECT 34 UNION SELECT 35 UNION SELECT 36 UNION SELECT 37 UNION SELECT 38 UNION SELECT 39
          UNION SELECT 40 UNION SELECT 41 UNION SELECT 42 UNION SELECT 43 UNION SELECT 44 UNION SELECT 45 UNION SELECT 46 UNION SELECT 47 UNION SELECT 48 UNION SELECT 49) a,
         (SELECT 0 AS n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9
          UNION SELECT 10 UNION SELECT 11 UNION SELECT 12 UNION SELECT 13 UNION SELECT 14 UNION SELECT 15 UNION SELECT 16 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19
          UNION SELECT 20 UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24 UNION SELECT 25 UNION SELECT 26 UNION SELECT 27 UNION SELECT 28 UNION SELECT 29) b
    WHERE (a.n + b.n*100) < 3000
) t;

INSERT INTO subscriptions (user_id, plan, status, monthly_price_cents)
SELECT user_id, plan, ELT(1+(user_id%3),'active','trial','cancelled'),
       CASE plan WHEN 'pro' THEN 1900 WHEN 'enterprise' THEN 9900 ELSE 0 END
FROM users;

INSERT INTO events (user_id, event_type, payload)
SELECT user_id,
       ELT(1+(user_id*7%5), 'login','page_view','click','purchase','error'),
       JSON_OBJECT('path', CONCAT('/page/', user_id%50))
FROM users
JOIN (SELECT 0 AS r UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) r;

SELECT plan, COUNT(*) FROM users GROUP BY plan;
"""

print("=== MySQL bulk insert ===")
print(summarise(call(MY_ARN, MY_LOAD, "seed-mysql-bulk")))

# PG: heavy queries to populate pg_stat_statements (so slow_queries demo finds something)
PG_HEAT = """Use the execute_sql tool to run each of these queries 3 times in a row. Just execute them, no commentary.

SELECT customer_id, count(*) FROM shop.orders WHERE status = 'paid' GROUP BY customer_id HAVING count(*) > 5;
SELECT o.order_id, oi.sku, oi.price_cents FROM shop.orders o JOIN shop.order_items oi ON oi.order_id = o.order_id WHERE o.status = 'paid' AND oi.price_cents > 5000;
SELECT email FROM shop.customers WHERE phone LIKE '%-019%';
ANALYZE shop.orders;
ANALYZE shop.order_items;
"""

print("\n=== PG heat queries ===")
print(summarise(call(PG_ARN, PG_HEAT, "seed-pg-heat")))

# Oracle: lightweight workload that's safe (no DDL on Oracle since user said don't touch)
OR_HEAT = """Run the following discovery actions and tell me what you find. Do NOT modify anything.

1. Use list_tablespaces.
2. Use get_active_sessions.
3. Use get_redo_log_status.
"""

print("\n=== Oracle warmup (read-only) ===")
print(summarise(call(OR_ARN, OR_HEAT, "seed-oracle-warmup")))
