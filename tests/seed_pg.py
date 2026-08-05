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

"""Seed Aurora PG (database-test) with a realistic e-commerce workload.

Creates customers + orders + order_items, inserts ~30k rows, then runs
queries that produce real findings for the demo:
  - sequential scans on a missing index (slow-query candidate)
  - dead tuples by deleting+updating without vacuum
  - long-running idle-in-transaction session left dangling
"""
import json, boto3, os, psycopg2, random, string, sys, time
from datetime import datetime, timedelta

# Make the repo root importable so the shared TLS posture is reused here
# instead of re-specified (or forgotten) per script.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.admin_ops.db.tls import postgres_ssl_kwargs  # noqa: E402

REGION = "us-east-1"
# Secrets Manager secret *name* (not a credential) — the value is fetched at runtime.
SECRET_ID = "dbops/aurora-pg/primary"  # nosec B105

sm = boto3.client("secretsmanager", region_name=REGION)
secret = json.loads(sm.get_secret_value(SecretId=SECRET_ID)["SecretString"])

conn = psycopg2.connect(host=secret["host"], port=secret["port"], user=secret["username"], password=secret["password"], dbname=secret["dbname"], connect_timeout=10, **postgres_ssl_kwargs(secret["host"]))
conn.autocommit = True
cur = conn.cursor()

print("creating schema and tables...")
cur.execute("CREATE SCHEMA IF NOT EXISTS shop;")
cur.execute("""
CREATE TABLE IF NOT EXISTS shop.customers (
    customer_id  SERIAL PRIMARY KEY,
    email        TEXT,
    full_name    TEXT,
    phone        TEXT,
    created_at   TIMESTAMP DEFAULT NOW()
);
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS shop.orders (
    order_id     SERIAL PRIMARY KEY,
    customer_id  INT,
    status       TEXT,
    total_cents  BIGINT,
    created_at   TIMESTAMP DEFAULT NOW()
);
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS shop.order_items (
    item_id     SERIAL PRIMARY KEY,
    order_id    INT,
    sku         TEXT,
    quantity    INT,
    price_cents BIGINT
);
""")

cur.execute("SELECT count(*) FROM shop.customers")
existing = cur.fetchone()[0]
if existing < 5000:
    print(f"seeding customers (currently {existing})...")
    rows = []
    for i in range(5000):
        rows.append((
            f"customer{i}@example.com",
            "".join(random.choices(string.ascii_letters, k=8)) + " " + "".join(random.choices(string.ascii_letters, k=10)),
            # 555-0100..555-0199 is the NANP range reserved for fiction;
            # 555-1000 and up are assignable to real subscribers.
            f"+1-555-{random.randint(100, 199):04d}",
        ))
    cur.executemany("INSERT INTO shop.customers (email, full_name, phone) VALUES (%s, %s, %s)", rows)
    print("  customers ok")

cur.execute("SELECT count(*) FROM shop.orders")
existing = cur.fetchone()[0]
if existing < 20000:
    print(f"seeding orders (currently {existing})...")
    rows = []
    statuses = ["placed", "paid", "shipped", "delivered", "cancelled"]
    for i in range(20000):
        rows.append((random.randint(1, 5000), random.choice(statuses), random.randint(500, 50000)))
    cur.executemany("INSERT INTO shop.orders (customer_id, status, total_cents) VALUES (%s, %s, %s)", rows)
    print("  orders ok")

cur.execute("SELECT count(*) FROM shop.order_items")
existing = cur.fetchone()[0]
if existing < 30000:
    print(f"seeding order_items (currently {existing})...")
    rows = []
    skus = [f"SKU-{i:04d}" for i in range(200)]
    for _ in range(30000):
        rows.append((random.randint(1, 20000), random.choice(skus), random.randint(1, 5), random.randint(100, 9999)))
    cur.executemany("INSERT INTO shop.order_items (order_id, sku, quantity, price_cents) VALUES (%s, %s, %s, %s)", rows)
    print("  order_items ok")

print("creating bloat: delete + update without vacuum")
cur.execute("DELETE FROM shop.order_items WHERE quantity = 1 AND item_id < 5000")
cur.execute("UPDATE shop.order_items SET price_cents = price_cents + 1 WHERE item_id BETWEEN 5000 AND 10000")

print("running heavy seq-scan query a few times to populate pg_stat_statements")
for _ in range(5):
    cur.execute("SELECT customer_id, count(*) FROM shop.orders WHERE status = 'paid' GROUP BY customer_id HAVING count(*) > 5")
    cur.fetchall()
    cur.execute("SELECT o.order_id, oi.sku, oi.price_cents FROM shop.orders o JOIN shop.order_items oi ON oi.order_id = o.order_id WHERE o.status = 'paid' AND oi.price_cents > 5000")
    cur.fetchall()
    cur.execute("SELECT email FROM shop.customers WHERE phone LIKE '%-019%'")
    cur.fetchall()

print("creating an idle-in-transaction session (so blocking-chain demo has data)")
conn2 = psycopg2.connect(host=secret["host"], port=secret["port"], user=secret["username"], password=secret["password"], dbname=secret["dbname"], **postgres_ssl_kwargs(secret["host"]))
cur2 = conn2.cursor()
cur2.execute("BEGIN")
cur2.execute("SELECT * FROM shop.orders WHERE order_id = 1 FOR UPDATE")
print("  idle txn left open (will be visible in active sessions / blocking chains)")

cur.execute("SELECT pg_database_size(current_database())")
size = cur.fetchone()[0]
print(f"db size: {size/1024/1024:.1f} MB")

print("done — agents will find: missing index on shop.orders(status), seq scans, dead tuples, idle txn")
