#!/usr/bin/env bash
# Deploy the SQL Server agent to AgentCore Runtime.
#
# Why this script exists
# ----------------------
# `direct_code_deploy` uploads only the agent directory, so the shared `src`
# package has to be copied in before the upload. The copy is staged and then
# removed again, for two reasons:
#
#   1. A second copy of `src/admin_ops/db/statements.py` inside the repository
#      defeats the drift guard in tests/admin_ops/db/test_statements.py, which
#      walks every .py file and exempts only the canonical path. Leaving the
#      copy in place turns that guard into a false pass.
#   2. Two editable copies of security-critical helpers invites edits to the
#      wrong one.
#
# The staged directory is also listed in .gitignore so it can never be
# committed, but the cleanup here is what keeps the working tree honest.
set -euo pipefail

: "${AWS_PROFILE:?Set AWS_PROFILE to an explicit deployment profile}"
: "${EXPECTED_AWS_ACCOUNT_ID:?Set EXPECTED_AWS_ACCOUNT_ID to the reviewed 12-digit account}"
: "${SQLSERVER_SECRET_ARN:?Set SQLSERVER_SECRET_ARN from the sqlserver-ec2 stack output}"
: "${SQLSERVER_EC2_INSTANCE_ID:?Set SQLSERVER_EC2_INSTANCE_ID from the sqlserver-ec2 stack output}"
: "${AGENTCORE_CLI:?Set AGENTCORE_CLI to the absolute path of the agentcore executable}"
: "${A2A_REGION:=us-east-1}"
: "${AGENT_NAME:=dbops_sqlserver}"
# true for runtimes that serve automated callers (AWS DevOps Agent): only the
# read-only tools are registered. Leave false for the interactive UI runtime.
: "${DBOPS_READ_ONLY_MODE:=false}"
# pymssql cannot verify the server certificate, so the connection is encrypted
# but unverified. Make the deployer acknowledge that rather than defaulting it.
if [[ "${DB_TLS_ALLOW_UNVERIFIED:-}" != "true" ]]; then
  echo "Set DB_TLS_ALLOW_UNVERIFIED=true to acknowledge that the SQL Server" >&2
  echo "connection is encrypted but its certificate is not verified (pymssql" >&2
  echo "has no CA bundle option). See README: SQL Server agent, Encryption in transit." >&2
  exit 2
fi
if [[ "$DBOPS_READ_ONLY_MODE" != "true" && "$DBOPS_READ_ONLY_MODE" != "false" ]]; then
  echo "DBOPS_READ_ONLY_MODE must be true or false" >&2
  exit 2
fi

if [[ ! "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "EXPECTED_AWS_ACCOUNT_ID must be a 12-digit AWS account ID" >&2
  exit 2
fi
if [[ "$AGENTCORE_CLI" != /* || ! -x "$AGENTCORE_CLI" ]]; then
  echo "AGENTCORE_CLI must be an executable absolute path" >&2
  exit 2
fi

caller="$(aws --profile "$AWS_PROFILE" --region "$A2A_REGION" sts get-caller-identity --query Account --output text)"
if [[ "$caller" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
  echo "AWS caller account '$caller' does not match EXPECTED_AWS_ACCOUNT_ID" >&2
  exit 2
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

cleanup() { rm -rf "$HERE/src"; }
trap cleanup EXIT

rm -rf "$HERE/src"
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$REPO_ROOT/src/" "$HERE/src/"
echo "Staged shared src/ into $HERE/src"

printf 'Caller account: %s\nProfile: %s\nAgent: %s\nRead-only mode: %s\n' "$caller" "$AWS_PROFILE" "$AGENT_NAME" "$DBOPS_READ_ONLY_MODE"

if [[ "${CONFIRM_AWS_MUTATIONS:-}" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
  echo "Plan only. To deploy, set CONFIRM_AWS_MUTATIONS to the exact reviewed account ID."
  exit 0
fi

cd "$HERE"
AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$A2A_REGION" "$AGENTCORE_CLI" deploy \
  --agent "$AGENT_NAME" \
  --env "SQLSERVER_SECRET_ARN=$SQLSERVER_SECRET_ARN" \
  --env "SQLSERVER_EC2_INSTANCE_ID=$SQLSERVER_EC2_INSTANCE_ID" \
  --env "DBOPS_READ_ONLY_MODE=$DBOPS_READ_ONLY_MODE" \
  --env "DB_TLS_ALLOW_UNVERIFIED=$DB_TLS_ALLOW_UNVERIFIED"
