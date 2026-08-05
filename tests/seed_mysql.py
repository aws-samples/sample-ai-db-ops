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

"""Seed Aurora MySQL with a realistic SaaS workload."""
import json, boto3, os, pymysql, random, string, sys

# Make the repo root importable so the shared TLS posture is reused here
# instead of re-specified (or forgotten) per script.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.admin_ops.db.tls import mysql_ssl_kwargs  # noqa: E402

REGION = "us-east-1"
# Secrets Manager secret *name* (not a credential) — the value is fetched at runtime.
SECRET_ID = "dbops/aurora-mysql/primary"  # nosec B105

sm = boto3.client("secretsmanager", region_name=REGION)
secret = json.loads(sm.get_secret_value(SecretId=SECRET_ID)["SecretString"])

conn = pymysql.connect(host=secret["host"], port=int(secret["port"]), user=secret["username"], password=secret["password"], connect_timeout=10, autocommit=True, **mysql_ssl_kwargs(secret["host"]))
cur = conn.cursor()

cur.execute("CREATE DATABASE IF NOT EXISTS appdb")
cur.execute("USE appdb")
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
    email      VARCHAR(255),
    full_name  VARCHAR(255),
    plan       VARCHAR(32),
    last_login DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS events (
    event_id   BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id    BIGINT,
    event_type VARCHAR(64),
    payload    JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS subscriptions (
    sub_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id    BIGINT,
    plan       VARCHAR(32),
    status     VARCHAR(32),
    monthly_price_cents INT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

cur.execute("SELECT count(*) FROM users")
n = cur.fetchone()[0]
if n < 3000:
    print(f"seeding users (have {n})...")
    rows = []
    plans = ["free", "pro", "enterprise"]
    for i in range(3000):
        rows.append((f"user{i}@example.com", "".join(random.choices(string.ascii_letters, k=12)), random.choice(plans)))
    cur.executemany("INSERT INTO users (email, full_name, plan) VALUES (%s, %s, %s)", rows)

cur.execute("SELECT count(*) FROM events")
n = cur.fetchone()[0]
if n < 25000:
    print(f"seeding events (have {n})...")
    rows = []
    types = ["login", "logout", "page_view", "click", "purchase", "signup", "error"]
    for _ in range(25000):
        rows.append((random.randint(1, 3000), random.choice(types), '{"path":"/dashboard"}'))
    cur.executemany("INSERT INTO events (user_id, event_type, payload) VALUES (%s, %s, %s)", rows)

cur.execute("SELECT count(*) FROM subscriptions")
n = cur.fetchone()[0]
if n < 1500:
    print(f"seeding subscriptions (have {n})...")
    rows = []
    for _ in range(1500):
        plan = random.choice(["pro", "enterprise"])
        price = 1900 if plan == "pro" else 9900
        rows.append((random.randint(1, 3000), plan, random.choice(["active", "cancelled", "trial"]), price))
    cur.executemany("INSERT INTO subscriptions (user_id, plan, status, monthly_price_cents) VALUES (%s, %s, %s, %s)", rows)

print("running heavy queries to populate performance_schema digests")
for _ in range(8):
    cur.execute("SELECT plan, count(*) FROM users GROUP BY plan")
    cur.fetchall()
    cur.execute("SELECT u.email, count(e.event_id) FROM users u LEFT JOIN events e ON e.user_id = u.user_id WHERE e.event_type = 'login' GROUP BY u.user_id, u.email ORDER BY count(e.event_id) DESC LIMIT 20")
    cur.fetchall()
    cur.execute("SELECT * FROM events WHERE event_type = 'error' AND payload LIKE '%dashboard%'")
    cur.fetchall()

print("creating long-running open txn (lock-wait demo)")
conn2 = pymysql.connect(host=secret["host"], port=int(secret["port"]), user=secret["username"], password=secret["password"], database="appdb", **mysql_ssl_kwargs(secret["host"]))
c2 = conn2.cursor()
c2.execute("START TRANSACTION")
c2.execute("SELECT * FROM users WHERE user_id = 1 FOR UPDATE")
print("  txn left open intentionally (innodb lock waits demo)")

print("done — MySQL has users / events / subscriptions seeded with realistic distributions")
