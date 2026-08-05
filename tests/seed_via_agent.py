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

"""Seed PG and MySQL by calling the agents' execute_sql tools.

Skips local connectivity — uses the same Bedrock AgentCore path the UI does.
"""
import boto3, json, sys, time

REGION = "us-east-1"
client = boto3.client("bedrock-agentcore", region_name=REGION)

PG_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/dbops_postgresql-XXXXXXXXXX"
MY_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/dbops_mysql-XXXXXXXXXX"

def call(arn, prompt, sid):
    payload = json.dumps({"prompt": prompt, "user_id": "dbops-user"})
    sid_padded = (sid + "-padded-padded-padded-padded-padded")[:48]
    r = client.invoke_agent_runtime(
        agentRuntimeArn=arn, qualifier="DEFAULT",
        runtimeSessionId=sid_padded, payload=payload,
    )
    body = r["response"].read().decode()
    return body[:2000]

# ---- PostgreSQL ----
PG_BLOCK = """Use the execute_sql tool to run the following statements in order. Do not summarize, just execute them.

CREATE SCHEMA IF NOT EXISTS shop;

CREATE TABLE IF NOT EXISTS shop.customers (
    customer_id  SERIAL PRIMARY KEY,
    email        TEXT,
    full_name    TEXT,
    phone        TEXT,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shop.orders (
    order_id     SERIAL PRIMARY KEY,
    customer_id  INT,
    status       TEXT,
    total_cents  BIGINT,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shop.order_items (
    item_id     SERIAL PRIMARY KEY,
    order_id    INT,
    sku         TEXT,
    quantity    INT,
    price_cents BIGINT
);

INSERT INTO shop.customers (email, full_name, phone)
SELECT 'cust' || n || '@example.com', 'Customer ' || n,
       -- 555-0100..555-0199 is the range the North American Numbering Plan
       -- reserves for fiction. 555-1000..555-9999 are assignable and could
       -- belong to a real person, so synthetic data must stay out of them.
       '+1-555-01' || lpad((n % 100)::text, 2, '0')
FROM generate_series(1, 5000) AS n
ON CONFLICT DO NOTHING;

INSERT INTO shop.orders (customer_id, status, total_cents)
SELECT (random()*4999+1)::int,
       (ARRAY['placed','paid','shipped','delivered','cancelled'])[1 + (random()*4)::int],
       (random()*49500 + 500)::bigint
FROM generate_series(1, 20000);

INSERT INTO shop.order_items (order_id, sku, quantity, price_cents)
SELECT (random()*19999+1)::int,
       'SKU-' || lpad(((random()*199)::int)::text, 4, '0'),
       (random()*4+1)::int,
       (random()*9899 + 100)::bigint
FROM generate_series(1, 30000);

DELETE FROM shop.order_items WHERE quantity = 1 AND item_id < 5000;
UPDATE shop.order_items SET price_cents = price_cents + 1 WHERE item_id BETWEEN 5000 AND 10000;
"""

# ---- MySQL ----
MY_BLOCK = """Use the execute_sql tool to run these statements in order. Do not summarize, just execute them.

CREATE DATABASE IF NOT EXISTS appdb;

USE appdb;

CREATE TABLE IF NOT EXISTS users (
    user_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
    email      VARCHAR(255),
    full_name  VARCHAR(255),
    plan       VARCHAR(32),
    last_login DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    event_id   BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id    BIGINT,
    event_type VARCHAR(64),
    payload    JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    sub_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id    BIGINT,
    plan       VARCHAR(32),
    status     VARCHAR(32),
    monthly_price_cents INT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

print("=== PG seed ===")
out = call(PG_ARN, PG_BLOCK, "seed-pg-001")
print(out)

print()
print("=== MySQL seed ===")
out = call(MY_ARN, MY_BLOCK, "seed-mysql-001")
print(out)
