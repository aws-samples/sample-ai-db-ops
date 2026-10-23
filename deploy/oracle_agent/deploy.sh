#!/usr/bin/env bash
# Deploy the Oracle agent to AgentCore Runtime.
#
# `direct_code_deploy` uploads only the agent directory, so two things are
# staged into it before the upload and removed again on exit:
#
#   * the shared `src` package (see deploy/sqlserver_agent/deploy.sh for why the
#     copy must not outlive the deploy), and
#   * the Amazon RDS CA bundle, as certs/ewallet.pem. python-oracledb Thin mode
#     reads trust anchors from a file of exactly that name in `wallet_location`,
#     and with it present the agent verifies the server certificate and host
#     name (SSL_SERVER_DN_MATCH=YES) instead of running encrypted-but-unverified.
#
# Oracle speaks TLS only on the TCPS listener (2484 on Amazon RDS, enabled by the
# SSL option in the instance's option group). ORACLE_TLS_PORT overrides the port
# recorded in the secret for secrets that record the plain 1521 listener.
set -euo pipefail
: "${AWS_PROFILE:?Set AWS_PROFILE to an explicit deployment profile}"
: "${EXPECTED_AWS_ACCOUNT_ID:?Set EXPECTED_AWS_ACCOUNT_ID to the reviewed 12-digit account}"
: "${ORACLE_SECRET_ARN:?Set ORACLE_SECRET_ARN to the dbops/oracle secret ARN}"
: "${ORACLE_DB_INSTANCE_IDENTIFIER:?Set ORACLE_DB_INSTANCE_IDENTIFIER to the one RDS instance this agent may act on}"
: "${AGENTCORE_CLI:?Set AGENTCORE_CLI to the absolute path of the agentcore executable}"
: "${A2A_REGION:=us-east-1}"
: "${AGENT_NAME:=dbops_oracle}"
: "${ORACLE_TLS_PORT:=2484}"
# true for runtimes that serve automated callers (AWS DevOps Agent): only the
# read-only tools are registered. Leave false for the interactive UI runtime.
: "${DBOPS_READ_ONLY_MODE:=false}"
RDS_CA_BUNDLE_URL="https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
if [[ "$DBOPS_READ_ONLY_MODE" != "true" && "$DBOPS_READ_ONLY_MODE" != "false" ]]; then
  echo "DBOPS_READ_ONLY_MODE must be true or false" >&2
  exit 2
fi
if [[ ! "$EXPECTED_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  echo "EXPECTED_AWS_ACCOUNT_ID must be a 12-digit AWS account ID" >&2
  exit 2
fi
if [[ ! "$ORACLE_DB_INSTANCE_IDENTIFIER" =~ ^[A-Za-z][A-Za-z0-9-]{0,62}$ ]]; then
  echo "ORACLE_DB_INSTANCE_IDENTIFIER is not a valid RDS DB instance identifier" >&2
  exit 2
fi
if [[ ! "$ORACLE_TLS_PORT" =~ ^[0-9]{1,5}$ ]]; then
  echo "ORACLE_TLS_PORT must be a TCP port number" >&2
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
cleanup() { rm -rf "$HERE/src" "$HERE/certs"; }
trap cleanup EXIT
cleanup
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$REPO_ROOT/src/" "$HERE/src/"
mkdir -p "$HERE/certs"
curl --fail --silent --show-error --proto '=https' --tlsv1.2 -o "$HERE/certs/ewallet.pem" "$RDS_CA_BUNDLE_URL"
if ! grep -q "BEGIN CERTIFICATE" "$HERE/certs/ewallet.pem"; then
  echo "Downloaded RDS CA bundle does not look like PEM certificates" >&2
  exit 2
fi
echo "Staged shared src/ and the RDS CA bundle into $HERE"
printf 'Caller account: %s\nProfile: %s\nAgent: %s\nRDS instance pin: %s\nRead-only mode: %s\n' \
  "$caller" "$AWS_PROFILE" "$AGENT_NAME" "$ORACLE_DB_INSTANCE_IDENTIFIER" "$DBOPS_READ_ONLY_MODE"
if [[ "${CONFIRM_AWS_MUTATIONS:-}" != "$EXPECTED_AWS_ACCOUNT_ID" ]]; then
  echo "Plan only. To deploy, set CONFIRM_AWS_MUTATIONS to the exact reviewed account ID."
  exit 0
fi
cd "$HERE"
AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$A2A_REGION" "$AGENTCORE_CLI" deploy \
  --agent "$AGENT_NAME" \
  --env "ORACLE_SECRET_ARN=$ORACLE_SECRET_ARN" \
  --env "ORACLE_DB_INSTANCE_IDENTIFIER=$ORACLE_DB_INSTANCE_IDENTIFIER" \
  --env "ORACLE_TLS_PORT=$ORACLE_TLS_PORT" \
  --env "DB_SSL_CA_BUNDLE=certs/ewallet.pem" \
  --env "DBOPS_READ_ONLY_MODE=$DBOPS_READ_ONLY_MODE"
