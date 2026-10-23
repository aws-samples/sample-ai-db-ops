# 🎮 Agentic DB Ops

AI-powered database operations platform using **Strands Agent Framework** on **Amazon Bedrock AgentCore Runtime**. Manage Aurora PostgreSQL, Aurora MySQL, Oracle EE, SQL Server on EC2, and DynamoDB through natural language with real-time connections to live databases.

> **Note:** This is sample code, for non-production usage. You should work with your
> security and legal teams to meet your organizational security, regulatory and
> compliance requirements before deployment.

This repo is configured for AWS account **`123456789012`** (`us-east-1`). All account-specific values are read from environment variables — see `ui/.env.local.example` and the deploy script header.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Next.js UI (localhost:3001)                                    │
│  ├── Agent selector (PostgreSQL / MySQL / Oracle /              │
│  │                   SQL Server / DynamoDB)                     │
│  ├── Database fleet panel with quick actions                    │
│  ├── Chat interface (natural language → agent tools)            │
│  ├── File upload (CSV/XLS/JSON → create table + load data)      │
│  └── Trace panel (real-time tool execution visibility)          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ boto3 → invoke_agent_runtime
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Amazon Bedrock AgentCore Runtime (VPC mode)                    │
│                                                                 │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐       │
│  │dbops_postgresql│ │  dbops_mysql   │ │  dbops_oracle  │       │
│  │  31 tools      │ │  24 tools      │ │  ~25 tools     │       │
│  │  Strands Agent │ │  Strands Agent │ │  Strands Agent │       │
│  └────────┬───────┘ └────────┬───────┘ └────────┬───────┘       │
│  ┌────────▼───────┐ ┌────────▼───────┐ ┌────────▼───────┐       │
│  │dbops_sqlserver │ │ dbops_dynamodb │ │  dbops_devops  │       │
│  │  26 tools      │ │  17 tools      │ │  (orchestrator)│       │
│  │  Strands Agent │ │  Strands Agent │ │  Strands Agent │       │
│  └────────┬───────┘ └────────┬───────┘ └────────┬───────┘       │
│           │                  │                  │               │
│  ┌────────▼──────────────────▼──────────────────▼─────────────┐ │
│  │              Existing VPC (vpc-0xxxxxxxxxxxxxxxx)          │ │
│  │  VPC Endpoints: Secrets Manager, DynamoDB, Bedrock,        │ │
│  │                 CloudWatch Logs, Monitoring, STS, RDS, S3  │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Live Databases (private subnets)                               │
│                                                                 │
│  🐘 aurora-postgres-primary (Aurora PostgreSQL)                 │
│  🦅 oracle-prod (Oracle EE 19c on RDS)                       │
│  🟦 dbops-sqlserver-ec2 (SQL Server 2022 on EC2, self-managed)  │
│  ⚡ dbops-orders / dbops-registry / dbops-gamification /        │
│     dbops-leaderboard (DynamoDB)                                │
└─────────────────────────────────────────────────────────────────┘
```

The **S3 gateway endpoint** is required, not optional. AgentCore runtimes
deployed with `direct_code_deploy` fetch their code bundle from S3, and a VPC
without an S3 endpoint or a NAT gateway gives the runtime no path to it. The
symptom is a runtime that reports `READY` but fails every invocation with
`Runtime initialization time exceeded` and an empty log stream, because the
container never binds its port. Gateway endpoints are free.

## Quick Start

### Prerequisites

- AWS credentials for account `123456789012` (`aws configure` or env vars)
- Python 3.12 with `boto3` (used by the UI's `/api/invoke`)
- `agentcore` CLI: `pip install 'bedrock-agentcore==1.19.0'` (pinned to match the
  hash-locked runtime requirements; 1.18.0 and earlier are affected by
  CVE-2026-16796)
- Node.js 20+

### 1. Deploy infrastructure

```bash
aws cloudformation deploy \
  --stack-name dbops \
  --template-file infra/cloudformation-123456789012.yaml \
  --parameter-overrides \
      OraclePassword=<your-oracle-password> \
      AuroraPGPassword=<your-aurora-pg-password> \
  --capabilities CAPABILITY_NAMED_IAM
```

This creates the VPC endpoints, Secrets Manager entries, and DynamoDB tables. It does **not** create new RDS instances — it points at the Oracle and Aurora PG you already have in `vpc-0xxxxxxxxxxxxxxxx`.

Capture the outputs for the next step:

```bash
aws cloudformation describe-stacks --stack-name dbops \
  --query 'Stacks[0].Outputs' --output table
```

### 2. Deploy Cognito authentication

`infra/cognito-auth.yaml` creates an administrator-provisioned Cognito user pool,
a public application client, and a managed-login domain. The client supports only
the OAuth 2.0 Authorization Code flow. The application generates PKCE S256,
state, and nonce values server-side and stores only signed HttpOnly cookies.
It never stores Cognito access or refresh tokens and never trusts a browser
identity header.

Choose a globally unique domain prefix, then deploy the stack only after reviewing
the target account and change set:

```bash
aws cloudformation deploy \
  --stack-name dbops-cognito-auth \
  --template-file infra/cognito-auth.yaml \
  --parameter-overrides \
      AppBaseUrl=https://your-app.example.com \
      CognitoDomainPrefix=<globally-unique-prefix>
```

Use the stack outputs for `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, and
`COGNITO_DOMAIN`. Store a randomly generated `AUTH_SESSION_SECRET` of at least
32 bytes in Secrets Manager and attach it to App Runner as a runtime secret.
Do not put the secret in `apprunner.yaml`, a Docker build argument, an image
`ENV`, or any `NEXT_PUBLIC_*` variable.

Self-sign-up is disabled and MFA is required. Create administrators out of band,
complete their first-login password and TOTP enrollment, then write their
immutable Cognito `sub` (not email or username) to the `dbops-admins` table.
Authentication alone does not grant the application admin role.

### 3. Deploy agents to AgentCore

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=123456789012

# From CF stack outputs
export AGENT_SUBNETS="subnet-0aaaaaaaaaaaaaaaa,subnet-0bbbbbbbbbbbbbbbb"
export AGENT_SECURITY_GROUPS="sg-0xxxxxxxxxxxxxxxx,sg-0yyyyyyyyyyyyyyyy"
export PG_SECRET_ARN="<PostgresSecretArn output>"
export ORACLE_SECRET_ARN="<OracleSecretArn output>"
export DYNAMODB_TABLE="dbops-orders"
# Optional, only if you have a MySQL cluster:
# export MYSQL_SECRET_ARN="<your-mysql-secret-arn>"

# Explicitly opt in to protected DynamoDB session and vector memory.
export ENABLE_DYNAMODB_MEMORY=1
export DYNAMODB_AGENT_EXECUTION_ROLE_NAME="<existing DynamoDB AgentCore execution role>"
# Optional overrides:
# export DYNAMODB_MEMORY_STACK_NAME=dbops-dynamodb-vector-memory
# export DYNAMODB_MEMORY_SCOPE=dbops-demo
# export DYNAMODB_MEMORY_RETENTION_DAYS=30

# Review the exact commands without contacting AWS or changing local state.
DRY_RUN=1 ./deploy_all.sh dynamodb

# Validate the caller account, template, and execution role using read-only APIs.
PREFLIGHT_ONLY=1 ./deploy_all.sh dynamodb

# Only after reviewing the plan, permit CloudFormation, vector-index, IAM-policy,
# and AgentCore runtime changes.
CONFIRM_AWS_MUTATIONS=YES ./deploy_all.sh dynamodb
```

The memory stack enables deletion protection, point-in-time recovery, encryption,
and a retain policy. The deployment script reads the table and index names from
stack outputs, creates or validates the DynamoDB vector index, binds the same
execution-role ARN to AgentCore, and then injects the memory configuration into
only the DynamoDB runtime. It does not add DynamoDB permissions to the UI or App
Runner role.

Production uses Amazon Cognito managed login with Authorization Code + PKCE.
Every page requires a signed HttpOnly application session, and API routes derive
the principal exclusively from the verified session's immutable Cognito `sub`.
Unsafe authenticated requests must carry an `Origin` exactly equal to
`APP_BASE_URL`. Configure the callback and logout URLs from the same exact origin;
do not derive redirects from the request `Host` header. The public
`/api/health` route exists only for the App Runner health probe.

#### SQL Server on EC2

The SQL Server target is created by its own stack, which provisions the
instance, its security group, an instance role, and the Secrets Manager entry:

```bash
aws cloudformation create-stack \
  --stack-name dbops-sqlserver-ec2 \
  --template-body file://infra/sqlserver-ec2.yaml \
  --parameters \
    ParameterKey=VpcId,ParameterValue=vpc-0xxxxxxxxxxxxxxxx \
    ParameterKey=SubnetId,ParameterValue=subnet-0xxxxxxxxxxxxxxxx \
    "ParameterKey=AgentSecurityGroupIds,ParameterValue=sg-0xxxxxxxxxxxxxxxx\,sg-0yyyyyyyyyyyyyyyy" \
  --capabilities CAPABILITY_IAM
```

Use a private subnet that routes through a NAT gateway, so the instance can
reach the Microsoft package repository, Secrets Manager and SSM over HTTPS. The
instance gets no public IP by default. For a throwaway test in a public subnet
with no NAT, add `ParameterKey=AssociatePublicIp,ParameterValue=true`. Port 1433
is opened only to the AgentCore security groups, so the instance is not
reachable from the internet either way.

The connection secret is encrypted with a customer managed KMS key that the
stack creates (output `SecretKmsKeyArn`). The instance role can use the key
only through Secrets Manager. Grant `kms:Decrypt` on it, with a `kms:ViaService`
condition for Secrets Manager, to every role that reads the secret.
`infra/agent-permissions-policy.json` and
`infra/dbops-readonly-specialist-roles.yaml` already do.

The **SA password is generated on the instance** and written to Secrets Manager
by the instance itself. It is never a stack parameter, so it does not appear in
the template, in stack events, or in any operator's terminal. The bootstrap
publishes the credentials as soon as they are known to work and before seeding,
so a seeding failure leaves a recoverable instance rather than a running
database whose password nobody holds.

SQL Server 2022 **Developer Edition** is used: licence-free for non-production
and exposing the full Enterprise DMV surface, so the diagnostic tools behave as
they would against Standard or Enterprise. SQL Server on Linux requires x86_64;
Graviton is not supported.

Then deploy the agent with the stack outputs:

```bash
export AWS_PROFILE=<deployment-profile>
export EXPECTED_AWS_ACCOUNT_ID=123456789012
export SQLSERVER_SECRET_ARN="<SecretArn output>"
export SQLSERVER_EC2_INSTANCE_ID="<InstanceId output>"
export AGENTCORE_CLI="$(pwd)/.venv/bin/agentcore"

# Review the plan first; it prints the resolved account and arguments.
./deploy/sqlserver_agent/deploy.sh

# Then permit the AgentCore runtime change.
CONFIRM_AWS_MUTATIONS=$EXPECTED_AWS_ACCOUNT_ID ./deploy/sqlserver_agent/deploy.sh
```

`deploy.sh` exists because `direct_code_deploy` uploads **only the agent
directory**, so the shared `src` package has to be staged into it before upload
and removed afterwards. The cleanup matters: a lingering second copy of
`src/admin_ops/db/statements.py` inside the repository would defeat the drift
guard in `tests/admin_ops/db/test_statements.py`, which walks every `.py` file
and exempts only the canonical path, turning that guard into a false pass.

#### Read-only runtimes for AWS DevOps Agent

The A2A adapters in `aws-devops-agent-db-ops` call a separate, read-only copy
of the Oracle and SQL Server specialists rather than the interactive runtimes
the UI uses. A read-only runtime is the same code deployed with
`DBOPS_READ_ONLY_MODE=true`:

- The agent registers the Tier 1/2 tools only. The Tier-3 tools are absent from
  its tool list, so a model steered by injected content cannot even propose
  them. The Tier-3 hook stays attached as a second layer.
- Payload `approvals` are ignored, so no caller can satisfy the approval gate.
- Before serving, the agent checks that no registered tool is classified as
  mutating by `src/hooks/tier3_gate.py`, and refuses to run if one is.
- The Oracle agent also requires `ORACLE_DB_INSTANCE_IDENTIFIER`, so its RDS
  and CloudWatch tools act on that one instance only.
- `infra/dbops-readonly-specialist-roles.yaml` provides execution roles that
  grant only Describe/Get actions, scoped to the pinned instance and secret.

```bash
# Execution roles (once)
aws cloudformation deploy --stack-name dbops-readonly-specialist-roles \
  --template-file infra/dbops-readonly-specialist-roles.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides OracleSecretArn=<arn> OracleDbInstanceIdentifier=<id> \
      SqlServerSecretArn=<arn> SqlServerSecretKmsKeyArn=<SecretKmsKeyArn output>

# Configure each agent once with `agentcore configure -n <name>_readonly -er <role ARN> ...`,
# then deploy:
cd deploy/sqlserver_agent
AGENT_NAME=dbops_sqlserver_readonly DBOPS_READ_ONLY_MODE=true bash deploy.sh
cd ../oracle_agent
AGENT_NAME=dbops_oracle_readonly DBOPS_READ_ONLY_MODE=true \
  ORACLE_DB_INSTANCE_IDENTIFIER=<id> bash deploy.sh
```

`deploy/oracle_agent/deploy.sh` also stages the Amazon RDS CA bundle as
`certs/ewallet.pem`, so the Oracle connection verifies the server certificate
and host name. The instance's `SSL` option must allow TLS 1.2 with a cipher
suite that current OpenSSL accepts, for example
`TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`.

After deploys finish, capture the runtime ARNs:

```bash
agentcore status -n dbops_postgresql
agentcore status -n dbops_oracle
agentcore status -n dbops_sqlserver
agentcore status -n dbops_dynamodb
```

### 4. Configure and start the UI

```bash
cd ui
cp .env.local.example .env.local
# Edit .env.local and paste the runtime ARNs you captured above.

npm ci          # installs exactly what package-lock.json pins
npm run dev
# UI runs at http://localhost:3001
```

### 5. Run E2E tests (optional)

```bash
bash tests/e2e_test.sh
```

## Configuration Reference

| Variable | Where | Purpose |
|---|---|---|
| `AWS_REGION` | UI + agents | AWS region (default `us-east-1`) |
| `AWS_ACCOUNT_ID` | UI | Used to derive default S3 upload bucket |
| `APP_BASE_URL` | UI | Exact application origin used for callback, logout, and origin validation |
| `COGNITO_USER_POOL_ID` | UI | Cognito user pool that issues ID tokens |
| `COGNITO_CLIENT_ID` | UI | Public Cognito OAuth client ID (no client secret) |
| `COGNITO_DOMAIN` | UI | HTTPS Cognito managed-login domain origin |
| `AUTH_SESSION_SECRET` | UI secret | At least 32 random bytes; App Runner runtime secret for signed cookies |
| `PYTHON_BIN` | UI | Path to Python interpreter for `/api/invoke` (default `python3.12`) |
| `POSTGRESQL_AGENT_ARN` | UI | AgentCore runtime ARN |
| `MYSQL_AGENT_ARN` | UI | AgentCore runtime ARN |
| `ORACLE_AGENT_ARN` | UI | AgentCore runtime ARN |
| `DYNAMODB_AGENT_ARN` | UI | AgentCore runtime ARN |
| `UPLOAD_BUCKET` | UI | Override S3 bucket for `/api/upload` |
| `PG_SECRET_ARN` | postgresql_agent | Secrets Manager ARN with `{host,port,username,password,dbname}` |
| `PG_DEV_SECRET_ARN` | postgresql_agent | Optional — required only for clone-to-dev tools |
| `MYSQL_SECRET_ARN` | mysql_agent | Secrets Manager ARN |
| `ORACLE_SECRET_ARN` | oracle_agent | Secrets Manager ARN with `{host,port,username,password,sid}` |
| `ORACLE_DB_INSTANCE_IDENTIFIER` | oracle_agent | Pins the RDS and CloudWatch tools to one instance; any other identifier is refused. Required in read-only mode |
| `ORACLE_TLS_PORT` | oracle_agent | Overrides the secret's port with the TCPS listener (2484 on Amazon RDS) |
| `DBOPS_READ_ONLY_MODE` | oracle_agent, sqlserver_agent | `true` builds the agent with Tier 1/2 tools only and ignores payload approvals (default `false`). See *Read-only runtimes for AWS DevOps Agent* |
| `DYNAMODB_TABLE` | dynamodb_agent | Default table for the agent (default `dbops-orders`) |
| `REPORTS_BUCKET` | reports | S3 bucket for archived reports — no default, must be set (see `config.yaml`) |
| `DB_SSL_CA_BUNDLE` | agents + library | CA bundle path for full certificate verification — see below |
| `DB_TLS_ALLOW_UNVERIFIED` | agents + library | Set `true` to accept encrypted-but-unverified TLS (default `false`) |
| `DB_REQUIRE_TLS` | agents + library | Set `false` to allow cleartext **to a loopback host only** (default `true`) |

### Encryption in transit

Database connections are encrypted by default, and the sample **will refuse to
connect** until you choose how the server certificate is verified. That is
deliberate — an unverified TLS connection does not protect against an active
man-in-the-middle, so it should be a visible decision rather than a silent
default. Pick one:

```bash
# Recommended: verify the certificate and hostname.
curl -o /etc/ssl/rds-global-bundle.pem \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
export DB_SSL_CA_BUNDLE=/etc/ssl/rds-global-bundle.pem

# Or, to get started quickly: encrypted but unverified.
export DB_TLS_ALLOW_UNVERIFIED=true
```

Verification needs the bundle because Amazon RDS and Aurora present
certificates from the Amazon RDS certificate authorities, which are not in the
operating system trust store.

`DB_REQUIRE_TLS=false` exists only for a local database that cannot speak TLS at
all. It is honoured **only when the host is a loopback address**; pointed at any
other host it is ignored and the connection stays encrypted, so the variable
cannot be used to put credentials on a network in cleartext. All of this lives
in one place: `src/admin_ops/db/tls.py`.

Oracle is the exception worth knowing about: it does not negotiate TLS on the
standard TCP listener, so the secret must point at the TCPS listener port
(2484 on Amazon RDS) rather than 1521.

## Capabilities

### 🐘 PostgreSQL Agent — 31 tools

| Category | Operations |
|----------|-----------|
| Monitoring | List databases, tables, connections, database size, CloudWatch metrics |
| Query Performance | Slow queries, active sessions, wait events, execution plans |
| Lock Management | Detect blocking chains, identify head blocker |
| Index Management | Missing indexes, unused indexes, index usage stats, create index concurrently, reindex concurrently |
| Space Management | Vacuum status, table bloat, dead tuples, execute vacuum |
| Security | Create/drop users, grant/revoke permissions, transaction ID wraparound check |
| Replication | Cluster info, replication status, create read replica |
| Scaling | Auto scaling (CPU-based), modify instance class, instance details |
| Data Operations | Execute SQL (DDL/DML), load CSV data, replicate tables with masking |
| Environment Mgmt | Clone to dev, data masking (partial/full/hash), share snapshots, backup |

### 🐬 MySQL Agent — 24 tools

| Category | Operations |
|----------|-----------|
| Monitoring | List databases, tables, connections, InnoDB status, CloudWatch metrics |
| Query Performance | Slow queries, processlist, index usage |
| Lock Management | Detect blocking chains (InnoDB lock waits) |
| Index Management | Recommend indexes, create index (`ALGORITHM=INPLACE`) |
| Security | Create/drop users, grant/revoke |
| Replication | Cluster info, create read replica |
| Scaling | Auto scaling, modify instance class |
| Data Operations | Execute SQL, load CSV, replicate with masking |
| Environment Mgmt | Clone to dev, data masking, share snapshots, backup |

### 🦅 Oracle Agent

| Category | Operations |
|----------|-----------|
| Schema | Tablespaces, segments, datafiles |
| Performance | ASH/AWR snapshots, top SQL, wait events, redo log status |
| Sessions | Active sessions, blocking, kill session |
| Index | Missing index recommendations, ONLINE creation |
| Maintenance | Gather stats, modify instance, on-demand backup |

### 🟦 SQL Server Agent — 26 tools

Targets **self-managed SQL Server 2022 on EC2**, not Amazon RDS. The agent is
otherwise structured like the RDS engines, with the same three tiers and the
same Tier-3 approval gate.

| Category | Operations |
|----------|-----------|
| Schema | Databases, schemas, tables with row counts and sizes |
| Performance | Wait statistics, slowest cached statements, execution plans by query hash |
| Sessions | Active requests, blocking chains, connection summary, kill session |
| Storage | Per-file IO latency, tempdb usage, database sizing |
| Memory | Memory clerks, page life expectancy, buffer cache counters |
| Index | Optimizer missing-index candidates, index usage, index creation |
| Maintenance | Update statistics, configuration changes, native copy-only backup |
| Infrastructure | EC2 instance details, `AWS/EC2` CloudWatch metrics |

**Three differences follow from the host being self-managed rather than RDS:**

1. **Instance metadata** comes from `ec2:DescribeInstances`, not
   `rds:DescribeDBInstances`. This requires an **EC2 interface VPC endpoint**;
   without one the call has no network path from a private subnet and times out.
2. **Host metrics** come from the `AWS/EC2` namespace, which exposes CPU,
   network, and EBS activity but **not memory or free storage** — those are
   guest-level figures needing the CloudWatch agent. Memory is therefore read
   from SQL Server's own DMVs via `get_memory_clerks`.
3. **No managed snapshot API.** `trigger_backup` performs a native
   `BACKUP DATABASE ... WITH COPY_ONLY`, so it does not disturb an existing
   differential or log backup chain, and `list_backups` reads `msdb` history.

**Driver.** `pymssql`, not `pyodbc`. `pymssql` ships manylinux aarch64 wheels
with FreeTDS bundled, so it needs no system package. `pyodbc` would additionally
require Microsoft's `msodbcsql` driver, which `direct_code_deploy` cannot
install.

**Encryption in transit.** TDS always encrypts the login packet, so the password
never crosses the network in cleartext. Whether the rest of the session is
encrypted is the server's decision and is only guaranteed with
`ForceEncryption` enabled. `pymssql` reads its TLS settings from `freetds.conf`
and exposes no per-connection CA bundle, so a remote connection is treated as
encrypted but **unverified** and requires `DB_TLS_ALLOW_UNVERIFIED=true`. A
configured `DB_SSL_CA_BUNDLE` cannot be applied through this driver and warns
rather than being silently ignored.

### ⚡ DynamoDB Agent — 17 tools

| Category | Operations |
|----------|-----------|
| Monitoring | List tables, describe table, CloudWatch metrics, TTL status |
| Performance | Throttled requests, hot partitions (Contributor Insights), GSI backpressure |
| Data Operations | Query by key, put item, batch write (25 items), scan samples |
| Schema Management | Add GSI, clone table structure |
| Scaling | Modify capacity (RCU/WCU), switch billing mode |
| Backup & Export | Create backup, export to S3, list backups |

## DBA & Admin Views

Beyond the per-engine agents (the **APP team** experience), the platform ships a
governance layer for **DBAs and security owners**:

### 🔐 Change Feed (`/admin/changes`)
A single, read-only, chronological audit trail of **every change that alters a SQL query
or database infrastructure**, normalized from four sources:
- **Git commits** (template/SQL changes), **CloudTrail** (infra changes),
- **agent Tier-3 actions** (what the agents executed), and
- **live PostgreSQL DDL** (ALTER / TRUNCATE / CREATE / DROP captured from CloudWatch logs).

Filterable by source, engine, and severity. Answers "what changed across the fleet, and
how risky was it?" in one screen.

### 🧭 DBA Knowledge Graph (`/dba`)
An admin-gated, read-only **single pane** that turns the Change Feed into a connected
graph (production: **Amazon Neptune** + openCypher; demo: an in-process seeded store, no
AWS required). One screen composes:
- a reverse-chronological **timeline** of change events,
- a **Graph Explorer** (React Flow) to drill from a change → the **table** it touched →
  the **principal** who ran it → the **Change Request ticket** that authorized it, and
- an **⚠️ Unticketed high-severity DDL** panel that proactively flags risky schema changes
  with **no Change Request behind them** — the headline governance signal.

Every `/api/dba/*` and `/api/kg/*` route is GET-only, admin-guarded, gating-checked
(fail-closed), and audited once per access. The whole feature is demoable in-process via
`ADMIN_DEV_BYPASS=1` with **no Neptune**.

Run it in-process with `ADMIN_DEV_BYPASS=1` to explore the DBA View without provisioning
Neptune; point `GraphBackend` at Neptune for a persistent deployment.

`ADMIN_DEV_BYPASS=1` also skips the `dbops-admins` check, so every signed-in user is
treated as an admin. The `Dockerfile` and `apprunner.yaml` leave it unset. Set it only
for a single-user demo on the seeded data, never on a shared deployment.

## Project Structure

```
.
├── deploy/
│   ├── postgresql_agent/    # Aurora/RDS PostgreSQL agent
│   ├── mysql_agent/         # Aurora/RDS MySQL agent
│   ├── oracle_agent/        # Oracle EE 19c on RDS
│   ├── sqlserver_agent/     # SQL Server 2022 on EC2 (self-managed)
│   ├── dynamodb_agent/      # DynamoDB agent
│   └── redis_agent/         # ElastiCache Redis agent (not yet wired in UI)
├── ui/
│   ├── .env.local.example   # Copy to .env.local and fill in
│   └── src/
│       ├── app/
│       │   ├── page.tsx
│       │   └── api/
│       │       ├── invoke/route.ts   # → AgentCore Runtime
│       │       └── upload/route.ts   # → S3
│       └── components/
│           ├── ChatPanel.tsx
│           ├── FleetPanel.tsx
│           ├── Sidebar.tsx
│           ├── GamificationBar.tsx
│           ├── TracePanel.tsx
│           ├── CloneModal.tsx
│           └── FileUpload.tsx
├── infra/
│   ├── cloudformation.yaml                  # Original (creates new RDS)
│   └── cloudformation-123456789012.yaml     # Account-specific (uses existing RDS)
├── deploy_all.sh
├── tests/e2e_test.sh
└── src/                     # Shared library (registry, hooks, gamification)
```

## Security Posture

- All databases live in private subnets — no public endpoints
- Agents run in **VPC mode**, in the same VPC as the databases
- Credentials live in **AWS Secrets Manager** — no values committed to source
- VPC endpoints for every AWS service the agents talk to — no internet egress
- Database connections are TLS-encrypted, fail-closed (see *Encryption in transit*)
- Tier 3 operations require explicit user approval, enforced programmatically by
  `Tier3ApprovalHook` on the Strands `BeforeToolCallEvent` bus — not by prompt text
- IAM least-privilege on agent execution roles
- VPC Flow Logs capture all traffic to a KMS-encrypted CloudWatch Logs group
  (`FlowLogRetentionDays`, default 365)
- Deletion protection is on for every Aurora cluster and RDS instance in
  `infra/cloudformation.yaml` (`EnableDeletionProtection`, default `true`)

## Before production

This is sample code. Beyond the review your organization requires, at minimum:

- Turn on rotation for the database secrets in Secrets Manager. The stacks create
  the secrets but no rotation schedule, because rotation needs a rotation function
  that can reach each database inside the private VPC.
- Replace the SQL Server `sa` login with a dedicated least-privilege login for the
  agents.
- Keep `EnableDeletionProtection=true` and leave `ADMIN_DEV_BYPASS` unset.

## Clean up

Deletion protection blocks `delete-stack` until you turn it off. Update the
stack with `EnableDeletionProtection=false`, then delete it:

```bash
aws cloudformation deploy --stack-name <stack-name> \
  --template-file infra/cloudformation.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides EnableDeletionProtection=false
aws cloudformation delete-stack --stack-name <stack-name>
```

`--parameter-overrides` keeps every other parameter at its previous value,
including `DBMasterPassword`.

## Tech Stack

| Component | Technology |
|---|---|
| Agent Framework | Strands Agents (Python) |
| Runtime | Amazon Bedrock AgentCore |
| LLM | Claude (via Bedrock) |
| Frontend | Next.js 16 + Tailwind CSS |
| Infrastructure | CloudFormation |
| Databases | Aurora PG, Oracle EE, DynamoDB (and Aurora MySQL when configured) |
| Credentials | AWS Secrets Manager |
| Networking | VPC + VPC Endpoints (fully private) |

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file.
