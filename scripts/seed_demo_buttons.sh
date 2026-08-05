#!/usr/bin/env bash
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

# Seed the demo with a couple of custom buttons per engine.
# Hits the local Next.js dev server. Safe to run multiple times — buttons
# are idempotent only by content, so re-running creates duplicates;
# delete the JSON state file first if needed.
set -euo pipefail
BASE="${BASE_URL:-http://localhost:3001}/api/admin/buttons"
H1="x-user-id: ${USER_ID:-dbops-user}"
H2="content-type: application/json"

post() {
  curl -sS -o /dev/null -w "%{http_code}\n" -X POST -H "$H1" -H "$H2" -d "$1" "$BASE"
}

# PostgreSQL
post '{"label":"Vacuum status","icon":"🧹","engine":"postgresql","target_scope":"global","body_kind":"sql","body":"SELECT relname, last_vacuum, last_autovacuum, n_dead_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 20","tier_hint":1,"confirmation_required":false}'
post '{"label":"Connections by state","icon":"📊","engine":"postgresql","target_scope":"global","body_kind":"sql","body":"SELECT state, COUNT(*) FROM pg_stat_activity GROUP BY state ORDER BY 2 DESC","tier_hint":1,"confirmation_required":false}'

# MySQL
post '{"label":"Long-running queries","icon":"🐢","engine":"mysql","target_scope":"global","body_kind":"sql","body":"SELECT id, user, host, db, time, state, info FROM information_schema.processlist WHERE time > 30 ORDER BY time DESC","tier_hint":1,"confirmation_required":false}'
post '{"label":"InnoDB lock waits","icon":"🔒","engine":"mysql","target_scope":"global","body_kind":"sql","body":"SELECT * FROM performance_schema.data_lock_waits LIMIT 50","tier_hint":1,"confirmation_required":false}'

# Oracle
post '{"label":"Tablespace usage","icon":"💾","engine":"oracle","target_scope":"global","body_kind":"sql","body":"SELECT tablespace_name, ROUND((tablespace_size - free_space)/tablespace_size * 100, 2) pct_used FROM dba_tablespace_usage_metrics ORDER BY pct_used DESC","tier_hint":1,"confirmation_required":false}'
post '{"label":"Top SQL by elapsed","icon":"🔥","engine":"oracle","target_scope":"global","body_kind":"sql","body":"SELECT sql_id, executions, ROUND(elapsed_time/1e6, 2) elapsed_s, ROUND(cpu_time/1e6, 2) cpu_s FROM v$sqlstats ORDER BY elapsed_time DESC FETCH FIRST 20 ROWS ONLY","tier_hint":1,"confirmation_required":false}'

# DynamoDB (prompt-mode — gets forwarded to the agent)
post '{"label":"Hot partition scan","icon":"🌡","engine":"dynamodb","target_scope":"global","body_kind":"prompt","body":"Scan the dbops-orders table and identify the top 5 hottest partition keys based on item count and total size","tier_hint":1,"confirmation_required":false}'
post '{"label":"Throttle review","icon":"🚦","engine":"dynamodb","target_scope":"global","body_kind":"prompt","body":"Review CloudWatch ThrottledRequests for the dbops-orders, dbops-registry, dbops-gamification, and dbops-leaderboard tables for the last 24h. Highlight any spikes and likely causes.","tier_hint":1,"confirmation_required":false}'

echo "Seeded buttons:"
for engine in postgresql mysql oracle dynamodb; do
  count=$(curl -sS -H "$H1" "$BASE?engine=$engine" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('buttons', [])))")
  echo "  $engine: $count"
done
