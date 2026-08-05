# 🎮 Agentic DB Ops

AI-powered database operations platform using **Strands Agent Framework** on **Amazon Bedrock AgentCore Runtime**. Manage Aurora PostgreSQL, Aurora MySQL, Oracle EE, and DynamoDB through natural language with real-time connections to live databases.

> **Note:** This is sample code, for non-production usage. You should work with your
> security and legal teams to meet your organizational security, regulatory and
> compliance requirements before deployment.

This repo is configured for AWS account **`123456789012`** (`us-east-1`). All account-specific values are read from environment variables — see `ui/.env.local.example` and the deploy script header.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Next.js UI (localhost:3001)                                    │
│  ├── Agent selector (PostgreSQL / MySQL / Oracle / DynamoDB)    │
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
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌───┐ │
│  │dbops_postgresql│ │  dbops_mysql   │ │  dbops_oracle  │ │…  │ │
│  │  31 tools      │ │  24 tools      │ │  ~25 tools     │ │   │ │
│  │  Strands Agent │ │  Strands Agent │ │  Strands Agent │ │   │ │
│  └────────┬───────┘ └────────┬───────┘ └────────┬───────┘ └─┬─┘ │
│           │                  │                  │           │   │
│  ┌────────▼──────────────────▼──────────────────▼───────────▼─┐ │
│  │              Existing VPC (vpc-0xxxxxxxxxxxxxxxx)          │ │
│  │  VPC Endpoints: Secrets Manager, DynamoDB, Bedrock,        │ │
│  │                 CloudWatch Logs, Monitoring, STS, RDS      │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Live Databases (private subnets)                               │
│                                                                 │
│  🐘 aurora-postgres-primary (Aurora PostgreSQL)                 │
│  🦅 oracle-prod (Oracle EE 19c on RDS)                       │
│  ⚡ dbops-orders / dbops-registry / dbops-gamification /        │
│     dbops-leaderboard (DynamoDB)                                │
└─────────────────────────────────────────────────────────────────┘
```

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

### 2. Deploy agents to AgentCore

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

./deploy_all.sh                    # deploys all four engines
# or, deploy only what you have credentials for:
./deploy_all.sh postgresql oracle dynamodb
```

After deploys finish, capture the runtime ARNs:

```bash
agentcore status -n dbops_postgresql
agentcore status -n dbops_oracle
agentcore status -n dbops_dynamodb
```

### 3. Configure and start the UI

```bash
cd ui
cp .env.local.example .env.local
# Edit .env.local and paste the runtime ARNs you captured above.

npm ci          # installs exactly what package-lock.json pins
npm run dev
# UI runs at http://localhost:3001
```

### 4. Run E2E tests (optional)

```bash
bash tests/e2e_test.sh
```

## Configuration Reference

| Variable | Where | Purpose |
|---|---|---|
| `AWS_REGION` | UI + agents | AWS region (default `us-east-1`) |
| `AWS_ACCOUNT_ID` | UI | Used to derive default S3 upload bucket |
| `NEXT_PUBLIC_USER_ID` | UI | Identity attached to chat + audit log (default `dbops-user`) |
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
  https://truststore.pki.rds.amazon.com/global/global-bundle.pem
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

## Project Structure

```
.
├── deploy/
│   ├── postgresql_agent/    # Aurora/RDS PostgreSQL agent
│   ├── mysql_agent/         # Aurora/RDS MySQL agent
│   ├── oracle_agent/        # Oracle EE 19c on RDS
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
