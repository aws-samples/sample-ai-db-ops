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

# Deploy AgentCore agents using supported AZs (use1-az4, use1-az1).
# Run from the repo root.
set -e

export AGENTCORE_SUPPRESS_RECOMMENDATION=1
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
ABS="${REPO_ROOT}/.venv/bin/agentcore"
SUBNETS="subnet-0xxxxxxxxxxxxxxxx,subnet-0yyyyyyyyyyyyyyyy"   # use1-az4, use1-az1
SGS="sg-0xxxxxxxxxxxxxxxx,sg-0yyyyyyyyyyyyyyyy"
REGION="us-east-1"

PG_SECRET_ARN="arn:aws:secretsmanager:us-east-1:123456789012:secret:dbops/aurora-pg/primary-XXXXXX"
MYSQL_SECRET_ARN="arn:aws:secretsmanager:us-east-1:123456789012:secret:dbops/aurora-mysql/primary-XXXXXX"
ORACLE_SECRET_ARN="arn:aws:secretsmanager:us-east-1:123456789012:secret:dbops/oracle/oracle-prod-XXXXXX"
DDB_TABLE="dbops-orders"

deploy_one() {
  local engine="$1"
  local agent_name="dbops_${engine}"
  local agent_dir="${REPO_ROOT}/deploy/${engine}_agent"
  shift
  local env_args=("$@")

  echo ""
  echo "========================================"
  echo "  Deploying ${agent_name}"
  echo "========================================"

  if [ ! -d "$agent_dir" ]; then
    echo "  ⚠️  Skipping ${engine} — directory missing"
    return
  fi

  cd "$agent_dir"
  # Clean any stale state
  rm -f .bedrock_agentcore.yaml
  rm -rf .bedrock_agentcore

  $ABS configure --entrypoint agent.py --name "$agent_name" \
    --vpc --subnets "$SUBNETS" --security-groups "$SGS" \
    --region "$REGION" --non-interactive >/tmp/${engine}_configure.log 2>&1
  if [ $? -ne 0 ]; then
    echo "  ❌ configure failed — see /tmp/${engine}_configure.log"
    tail -n 10 /tmp/${engine}_configure.log
    return 1
  fi
  echo "  ✓ configured"

  # Build env arg list
  local args=()
  for kv in "${env_args[@]}"; do
    args+=("--env" "$kv")
  done
  args+=("--env" "AWS_REGION=$REGION")
  args+=("--auto-update-on-conflict")

  $ABS deploy "${args[@]}" > /tmp/${engine}_deploy.log 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "  ❌ deploy failed (exit $rc) — see /tmp/${engine}_deploy.log"
    tail -n 20 /tmp/${engine}_deploy.log
    return 1
  fi
  echo "  ✓ deployed"
  grep -E "Agent created/updated|runtime/" /tmp/${engine}_deploy.log | tail -n 1
  cd "$REPO_ROOT"
}

deploy_one postgresql "PG_SECRET_ARN=${PG_SECRET_ARN}"
deploy_one mysql      "MYSQL_SECRET_ARN=${MYSQL_SECRET_ARN}"
deploy_one oracle     "ORACLE_SECRET_ARN=${ORACLE_SECRET_ARN}"
deploy_one dynamodb   "DYNAMODB_TABLE=${DDB_TABLE}"

echo ""
echo "========================================"
echo "  All deploys finished. Listing agents:"
echo "========================================"
$ABS configure list 2>/dev/null || true
