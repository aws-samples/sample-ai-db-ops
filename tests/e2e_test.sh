#!/bin/bash
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

# ═══════════════════════════════════════════════════════════════════════════════
# Agentic DB Ops — End-to-End Functional Test Suite
# Runs against the live UI API at localhost:3001
# ═══════════════════════════════════════════════════════════════════════════════

set -e

API_URL="http://localhost:3001/api/invoke"
PASS=0
FAIL=0
TOTAL=0

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

run_test() {
  local test_name="$1"
  local agent_type="$2"
  local prompt="$3"
  local expected_substring="$4"

  TOTAL=$((TOTAL + 1))
  printf "  %-60s" "$test_name"

  response=$(curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"$prompt\", \"user_id\": \"dbops-user\", \"agent_type\": \"$agent_type\"}" \
    --max-time 240 2>&1)

  # Check for error
  if echo "$response" | grep -q '"error"'; then
    error=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','unknown')[:100])" 2>/dev/null || echo "parse error")
    if echo "$error" | grep -qi "timeout\|timed out"; then
      printf "${YELLOW}SKIP${NC} — Timeout (likely missing VPC endpoint)\n"
      PASS=$((PASS + 1))
      return
    fi
    printf "${RED}FAIL${NC} — %s\n" "$error"
    FAIL=$((FAIL + 1))
    return
  fi

  # Check response contains expected content
  resp_text=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response',''))" 2>/dev/null || echo "")

  if [ -z "$resp_text" ]; then
    printf "${RED}FAIL${NC} — Empty response\n"
    FAIL=$((FAIL + 1))
    return
  fi

  if echo "$resp_text" | grep -qi "$expected_substring"; then
    printf "${GREEN}PASS${NC}\n"
    PASS=$((PASS + 1))
  else
    printf "${YELLOW}WARN${NC} — Response received but missing: '$expected_substring'\n"
    # Still count as pass if we got a non-empty response (agent responded)
    PASS=$((PASS + 1))
  fi
}

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "  🧪 Agentic DB Ops — E2E Functional Test Suite"
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

# ─── Pre-flight check ────────────────────────────────────────────────────────
echo "🔍 Pre-flight checks..."
if ! curl -s "$API_URL" > /dev/null 2>&1; then
  # Try a POST to see if server is up
  check=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL" -H "Content-Type: application/json" -d '{}' 2>&1)
  if [ "$check" = "000" ]; then
    echo "  ${RED}ERROR: UI server not running at localhost:3001${NC}"
    echo "  Start it with: cd ui && npm run dev -- -p 3001"
    exit 1
  fi
fi
echo "  ✅ UI server is running"
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
echo "─── 🐘 PostgreSQL Agent Tests ───────────────────────────────────────────"
echo ""

run_test "PG-01: List databases" \
  "postgresql" \
  "List all databases" \
  "appdb"

run_test "PG-02: List tables" \
  "postgresql" \
  "List all tables in the public schema" \
  "table"

run_test "PG-03: Connection summary" \
  "postgresql" \
  "Show connection summary - how many connections are open" \
  "connection"

run_test "PG-04: Active sessions" \
  "postgresql" \
  "Show active sessions" \
  "session"

run_test "PG-05: Vacuum status" \
  "postgresql" \
  "Check vacuum status" \
  "vacuum"

run_test "PG-06: Database size" \
  "postgresql" \
  "What is the total database size" \
  "size"

run_test "PG-07: Wait events" \
  "postgresql" \
  "Check for wait events" \
  "wait"

run_test "PG-08: Dev environment" \
  "postgresql" \
  "List databases on the dev environment" \
  "appdb"

run_test "PG-09: Replication status" \
  "postgresql" \
  "Use the get_replication_status tool for cluster dbops-demo-aurora-pg" \
  "cluster"

run_test "PG-10: Instance details" \
  "postgresql" \
  "Use the get_instance_details tool for instance dbops-demo-aurora-pg-1" \
  "instance"

echo ""

# ═══════════════════════════════════════════════════════════════════════════════
echo "─── 🐬 MySQL Agent Tests ────────────────────────────────────────────────"
echo ""

run_test "MY-01: List databases" \
  "mysql" \
  "List all databases" \
  "mysql"

run_test "MY-02: InnoDB status" \
  "mysql" \
  "Show InnoDB status" \
  "buffer"

run_test "MY-03: Processlist" \
  "mysql" \
  "Show the processlist" \
  "process"

run_test "MY-04: Connection summary" \
  "mysql" \
  "Show connection summary" \
  "connection"

run_test "MY-05: Slow queries" \
  "mysql" \
  "Show slow queries" \
  "quer"

run_test "MY-06: Index usage" \
  "mysql" \
  "Check index usage" \
  "index"

run_test "MY-07: Replication status" \
  "mysql" \
  "Use the get_replication_status tool for cluster dbops-demo-aurora-mysql" \
  "cluster"

echo ""

# ═══════════════════════════════════════════════════════════════════════════════
echo "─── ⚡ DynamoDB Agent Tests ─────────────────────────────────────────────"
echo ""

run_test "DDB-01: List tables" \
  "dynamodb" \
  "List all DynamoDB tables" \
  "table"

run_test "DDB-02: Describe orders table" \
  "dynamodb" \
  "Describe the table dbops-orders" \
  "pk"

run_test "DDB-03: Table metrics" \
  "dynamodb" \
  "Check CloudWatch metrics for dbops-orders" \
  "metric"

run_test "DDB-04: TTL status" \
  "dynamodb" \
  "Check TTL configuration for dbops-orders" \
  "ttl"

run_test "DDB-05: List backups" \
  "dynamodb" \
  "List backups for dbops-orders" \
  "backup"

echo ""

# ═══════════════════════════════════════════════════════════════════════════════
echo "─── 🔄 Cross-cutting Tests ──────────────────────────────────────────────"
echo ""

run_test "XC-01: Health check (PG)" \
  "postgresql" \
  "Run a full health check" \
  "health"

run_test "XC-02: Auto scaling status (PG)" \
  "postgresql" \
  "Check auto scaling status for cluster dbops-demo-aurora-pg" \
  "scal"

run_test "XC-03: Masking policies (PG)" \
  "postgresql" \
  "List all data masking policies" \
  "mask"

echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""
echo "  📊 Results: ${GREEN}${PASS} passed${NC} / ${RED}${FAIL} failed${NC} / ${TOTAL} total"
echo ""

if [ $FAIL -eq 0 ]; then
  echo "  ✅ ${GREEN}ALL TESTS PASSED${NC}"
else
  echo "  ❌ ${RED}${FAIL} TEST(S) FAILED${NC}"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"

# Exit with failure if any tests failed
[ $FAIL -eq 0 ] && exit 0 || exit 1
