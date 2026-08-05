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

# Deploy all DB Ops agents to Amazon Bedrock AgentCore Runtime.
#
# Prerequisites:
#   # The `agentcore` CLI used below (see `agentcore configure` / `agentcore
#   # deploy`) is provided by the starter toolkit, NOT by the bedrock-agentcore
#   # runtime library. Verified against 0.3.9.
#   pip install 'bedrock-agentcore-starter-toolkit==0.3.9'
#
#   # The bedrock-agentcore *runtime* library is installed inside each deployed
#   # agent image, not here. Its pin is declared once, in
#   # deploy/<agent>/requirements.in, and hash-locked into the matching
#   # requirements.txt — that pair is the authoritative source. Deliberately not
#   # restated here: a version repeated in prose drifts from the lock silently,
#   # and the note about CVE-2026-16796 (affecting 1.18.0 and earlier) lives
#   # beside the pin it justifies.
#
#   aws configure (with credentials for your own account)
#
# Required environment variables (looked up from your CloudFormation stack):
#   AGENT_SUBNETS          comma-separated, e.g. "subnet-0aaaaaaaaaaaaaaaa,subnet-0bbbbbbbbbbbbbbbb"
#   AGENT_SECURITY_GROUPS  comma-separated, e.g. "sg-0xxxxxxxxxxxxxxxx,sg-0yyyyyyyyyyyyyyyy"
#   PG_SECRET_ARN          PostgresSecretArn output from the CF stack
#   MYSQL_SECRET_ARN       MySQL Secrets Manager ARN (only if you have a MySQL cluster)
#   ORACLE_SECRET_ARN      OracleSecretArn output from the CF stack
#   DYNAMODB_TABLE         e.g. "dbops-orders"
#
# Usage:
#   chmod +x deploy_all.sh
#   ./deploy_all.sh                   # deploys all engines that have required env vars set
#   ./deploy_all.sh postgresql oracle # deploys only the listed engines

set -e

# Engines requested via argv, or all four by default
ENGINES=("$@")
if [ ${#ENGINES[@]} -eq 0 ]; then
  ENGINES=(postgresql mysql oracle dynamodb)
fi

if [ -z "${AGENT_SUBNETS:-}" ] || [ -z "${AGENT_SECURITY_GROUPS:-}" ]; then
  echo "❌ AGENT_SUBNETS and AGENT_SECURITY_GROUPS must be set."
  echo "   Look them up from the CloudFormation stack outputs:"
  echo "     aws cloudformation describe-stacks --stack-name dbops --query 'Stacks[0].Outputs'"
  exit 1
fi

deploy_agent() {
  local engine="$1"
  local name="dbops_${engine}"
  local dir="deploy/${engine}_agent"

  if [ ! -d "$dir" ]; then
    echo "  ⚠️  Skipping $engine — directory $dir not found"
    return
  fi

  echo "──────────────────────────────────────"
  echo "Deploying: $name"
  echo "──────────────────────────────────────"
  ( cd "$dir" && \
    agentcore configure \
      --entrypoint agent.py \
      --name "$name" \
      --vpc \
      --subnets "$AGENT_SUBNETS" \
      --security-groups "$AGENT_SECURITY_GROUPS" \
      --non-interactive && \
    agentcore deploy
  )
  echo "✅ $name deployed"
  echo ""
}

echo "========================================="
echo "  DB Ops — Deploying Agents to AgentCore"
echo "  Account: ${AWS_ACCOUNT_ID:-123456789012}"
echo "  Region:  ${AWS_REGION:-us-east-1}"
echo "========================================="
echo ""

for engine in "${ENGINES[@]}"; do
  deploy_agent "$engine"
done

echo "========================================="
echo "  All requested agents deployed!"
echo "========================================="
echo ""
echo "Next steps:"
echo "  1. Get the Runtime ARNs:"
echo "     agentcore status -n dbops_postgresql"
echo "  2. Add them to ui/.env.local (POSTGRESQL_AGENT_ARN, MYSQL_AGENT_ARN, etc.)"
echo "  3. Start the UI:  cd ui && npm ci && npm run dev -- -p 3001"
echo "     (npm ci installs exactly what package-lock.json pins; npm install"
echo "      may resolve newer, untested versions)"
echo ""
