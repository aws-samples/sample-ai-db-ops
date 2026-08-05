# Agentic DB Ops — Gamified Edition

## 1. Overview

Build a **gamified AI-powered database operations agent** using **Strands Agent Framework** deployed on **Amazon Bedrock AgentCore Runtime**. The agent enables teams to monitor, troubleshoot, and manage AWS databases using natural language — with no execution time limitations.

The gamified layer adds progression, achievements, and scoring to incentivize proactive database health management and reward good operational practices.

---

## 2. Goals

- Reduce mean time to diagnose (MTTD) database performance issues
- Provide a unified natural language interface across all AWS database engines
- **No timeout constraints** — AgentCore Runtime supports sessions up to 8 hours
- Enforce safety through tiered access (read → advise → act with approval)
- Eliminate the need for deep engine-specific expertise for common operations
- Maintain full audit trail of all agent actions
- **Gamify DB operations** — drive proactive behavior through XP, levels, achievements, and leaderboards

---

## 3. Technology Stack

### 3.1 Decision: Strands Agent Framework + AgentCore Runtime

| Criteria | Bedrock Agent (Action Groups) | Strands + AgentCore Runtime | Winner |
|---|---|---|---|
| Execution timeout | 15 min (Lambda) | **Up to 8 hours** | Strands + AgentCore |
| Framework flexibility | Locked to Bedrock SDK | Open-source, any model provider | Strands + AgentCore |
| Tool definition | OpenAPI schema + Lambda | Python decorators (`@tool`) | Strands + AgentCore |
| Long-running DB ops | Requires Step Functions workaround | Native — no workaround needed | Strands + AgentCore |
| Session isolation | Managed | **Built-in per-session isolation** | Tie |
| Deployment | Lambda/API Gateway | Code upload or container | Strands + AgentCore |
| Observability | CloudWatch + X-Ray | CloudWatch native integration | Tie |
| Hooks & steering | None | **Built-in lifecycle hooks** | Strands + AgentCore |
| MCP support | Not native | **Native MCP server integration** | Strands + AgentCore |
| Cost model | Per-invocation | **Pay-per-use (active resources only)** | Tie |
| Custom guardrails | Bedrock Guardrails (separate) | **Hooks + steering handlers inline** | Strands + AgentCore |

### 3.2 Why AgentCore Runtime Over Lambda

| Limitation Removed | Impact on DB Ops |
|---|---|
| No 15-min timeout | Index creation, VACUUM FULL, DBCC CHECKDB run to completion natively |
| No Step Functions workaround | Simplifies architecture — single agent handles full lifecycle |
| Session persistence (up to 8 hrs) | Multi-step investigations keep context without re-querying |
| Built-in memory service | Agent remembers prior findings within and across sessions |
| Policy engine (Cedar) | Enforce "never DROP in production" as runtime policy, not just prompt engineering |

### 3.3 Why Strands Agent Framework

| Capability | Benefit for DB Ops |
|---|---|
| `@tool` decorator | Define DB operations as simple Python functions |
| Lifecycle hooks | Intercept before tool execution (safety checks, audit logging) |
| Steering handlers | Self-correction when query returns unexpected results |
| MCP server support | Connect to existing monitoring MCP servers (Grafana, DataDog, etc.) |
| Model agnostic | Use Claude (Bedrock), but swap to other models if needed |
| Hot reloading | Add new DB tools without redeployment |
| Streaming | Real-time progress for long-running operations |

### 3.4 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Amazon Bedrock AgentCore                                            │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ AgentCore Runtime (up to 8-hour sessions)                     │  │
│  │                                                               │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │ Strands Agent (Python)                                  │  │  │
│  │  │                                                         │  │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │  │  │
│  │  │  │ Schema   │ │ Perf     │ │ Index    │ │ Maint    │  │  │  │
│  │  │  │ Tools    │ │ Tools    │ │ Tools    │ │ Tools    │  │  │  │
│  │  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │  │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │  │  │
│  │  │  │ Gamify   │ │ Policy   │ │ Memory   │ │ MCP      │  │  │  │
│  │  │  │ Engine   │ │ Hooks    │ │ Service  │ │ Servers  │  │  │  │
│  │  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌────────────┐  ┌────────────┐  ┌──────────────┐                  │
│  │ Gateway    │  │ Policy     │  │ Memory       │                  │
│  │ (MCP+APIs) │  │ Engine     │  │ Service      │                  │
│  └────────────┘  └────────────┘  └──────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐
│ AWS Databases│   │ CloudWatch / │   │ Gamification Store   │
│ (RDS, Aurora,│   │ Perf Insights│   │ (DynamoDB)           │
│ DynamoDB,    │   │              │   │ XP, Levels, Badges   │
│ Redshift,    │   └──────────────┘   └──────────────────────┘
│ ElastiCache, │
│ DocumentDB)  │
└──────────────┘
```

---

## 4. Supported Database Engines

| Engine | Service | Priority |
|---|---|---|
| PostgreSQL | Amazon RDS, Aurora | P0 |
| MySQL | Amazon RDS, Aurora | P0 |
| SQL Server | Amazon RDS, EC2 | P1 |
| DynamoDB | Amazon DynamoDB | P1 |
| Redshift | Amazon Redshift | P2 |
| Redis | Amazon ElastiCache | P2 |
| MongoDB-compatible | Amazon DocumentDB | P3 |

---

## 5. Functional Requirements

### 5.1 Schema Discovery

| ID | Requirement | Engines |
|---|---|---|
| FR-001 | List all databases/tables/collections in a target instance | All |
| FR-002 | Describe table schema (columns, types, constraints) | Relational |
| FR-003 | Show relationships (foreign keys, references) | Relational |
| FR-004 | Describe DynamoDB table (keys, GSIs, LSIs) | DynamoDB |
| FR-005 | List collections and indexes | DocumentDB |

### 5.2 Performance Monitoring

| ID | Requirement | Engines |
|---|---|---|
| FR-010 | Identify top N slow/expensive queries | All (except ElastiCache) |
| FR-011 | Show current active sessions and their state | Relational |
| FR-012 | Report wait statistics and wait types | Relational |
| FR-013 | Show CloudWatch metrics (CPU, memory, IOPS, connections) | All |
| FR-014 | Integrate with RDS Performance Insights | RDS/Aurora |
| FR-015 | Report DynamoDB consumed capacity and throttling | DynamoDB |
| FR-016 | Show Redshift query queue wait times and WLM metrics | Redshift |
| FR-017 | Report Redis memory usage, evictions, and hit ratio | ElastiCache |

### 5.3 Blocking & Contention

| ID | Requirement | Engines |
|---|---|---|
| FR-020 | Identify blocking sessions and head blockers | Relational |
| FR-021 | Show deadlock history/graphs | SQL Server, PostgreSQL |
| FR-022 | Report lock waits and duration | Relational |
| FR-023 | Identify DynamoDB hot partitions | DynamoDB |
| FR-024 | Show Redis slow commands | ElastiCache |

### 5.4 Index Analysis

| ID | Requirement | Engines |
|---|---|---|
| FR-030 | Identify missing indexes with impact score | Relational |
| FR-031 | Identify unused indexes (candidates for removal) | Relational |
| FR-032 | Report index fragmentation | SQL Server |
| FR-033 | Report table bloat and sequential scan ratios | PostgreSQL |
| FR-034 | Analyze Redshift distribution key and sort key effectiveness | Redshift |
| FR-035 | Report DynamoDB GSI usage and backpressure | DynamoDB |

### 5.5 Capacity & Storage

| ID | Requirement | Engines |
|---|---|---|
| FR-040 | Report table/database sizes and growth trends | All |
| FR-041 | Predict storage exhaustion based on growth rate | All |
| FR-042 | Report DynamoDB provisioned vs consumed capacity | DynamoDB |
| FR-043 | Show Redshift disk usage and node utilization | Redshift |
| FR-044 | Report Redis memory fragmentation ratio | ElastiCache |

### 5.6 Maintenance Operations

| ID | Requirement | Engines |
|---|---|---|
| FR-050 | Report vacuum/autovacuum status and dead tuples | PostgreSQL |
| FR-051 | Report backup status and last successful backup | All |
| FR-052 | Show SQL Agent job status and failures | SQL Server |
| FR-053 | Report DynamoDB TTL configuration and status | DynamoDB |
| FR-054 | Show Redshift VACUUM and ANALYZE status | Redshift |

### 5.7 Advisory Recommendations (Tier 2)

| ID | Requirement | Engines |
|---|---|---|
| FR-060 | Generate CREATE INDEX recommendations with DDL | Relational |
| FR-061 | Suggest query rewrites for slow queries | Relational |
| FR-062 | Recommend capacity scaling (up/down/out) | All |
| FR-063 | Suggest DynamoDB access pattern optimizations | DynamoDB |
| FR-064 | Recommend Redshift distribution/sort key changes | Redshift |
| FR-065 | Suggest Redis eviction policy changes | ElastiCache |

### 5.8 Actioned Operations (Tier 3 — Requires Approval)

| ID | Requirement | Engines |
|---|---|---|
| FR-070 | Execute approved index creation/deletion | Relational |
| FR-071 | Execute VACUUM / ANALYZE | PostgreSQL, Redshift |
| FR-072 | Update statistics | SQL Server, PostgreSQL |
| FR-073 | Kill blocking sessions (with confirmation) | Relational |
| FR-074 | Modify DynamoDB provisioned capacity | DynamoDB |
| FR-075 | Trigger on-demand backup | All |

**Note:** With AgentCore Runtime (8-hour sessions), Tier 3 operations run natively without async workarounds. The agent maintains the DB connection and streams progress in real-time.

---

## 6. Gamification Requirements

### 6.1 XP & Leveling System

| ID | Requirement |
|---|---|
| GF-001 | Users earn XP for each database operation performed through the agent |
| GF-002 | XP scales by operation complexity (Tier 1: 10 XP, Tier 2: 25 XP, Tier 3: 50 XP) |
| GF-003 | Bonus XP for proactive health checks (before issues become incidents) |
| GF-004 | Level progression: Intern → Junior DBA → DBA → Senior DBA → DB Architect → DB Legend |
| GF-005 | Each level unlocks new agent capabilities or faster access to Tier 3 operations |

### 6.2 Achievements & Badges

| ID | Badge | Criteria |
|---|---|---|
| GF-010 | 🔍 First Blood | Complete first performance diagnosis |
| GF-011 | 🏥 Healer | Resolve a blocking session that lasted > 5 minutes |
| GF-012 | ⚡ Speed Demon | Optimize a query that improved by > 50% |
| GF-013 | 🧹 Janitor | Remove 5+ unused indexes |
| GF-014 | 🔮 Oracle | Predict a capacity issue before it triggered an alarm |
| GF-015 | 🛡️ Guardian | Prevent a potential outage (detected before impact) |
| GF-016 | 🎯 Sniper | Fix an issue in a single agent interaction (no back-and-forth) |
| GF-017 | 🌍 Polyglot | Operate on 3+ different database engines in one session |
| GF-018 | 🔥 Streak Master | Perform health checks 5 days in a row |
| GF-019 | 🏆 Zero Downtime | Maintain 30-day streak with no critical incidents |
| GF-020 | 🧙 Wizard | Complete all achievements for a single engine |

### 6.3 Leaderboard & Teams

| ID | Requirement |
|---|---|
| GF-030 | Individual leaderboard ranked by XP within time period (weekly/monthly) |
| GF-031 | Team leaderboard (teams defined by `team_owner` in DB registry) |
| GF-032 | "Database Health Score" per database — reflects proactive maintenance |
| GF-033 | Weekly digest notification with rank changes and new achievements |
| GF-034 | Seasonal challenges (e.g., "Index Cleanup Sprint" — most unused indexes removed in a week) |

### 6.4 Quests & Missions

| ID | Quest | Description | XP Reward |
|---|---|---|---|
| GF-040 | Daily Health Check | Run performance check on all assigned databases | 50 XP |
| GF-041 | Index Audit | Review and resolve all missing index recommendations | 200 XP |
| GF-042 | Capacity Forecast | Generate capacity report for all P0 databases | 150 XP |
| GF-043 | Dead Weight | Identify and remove all unused indexes in a database | 300 XP |
| GF-044 | Bloat Buster | Resolve table bloat across assigned PostgreSQL databases | 250 XP |
| GF-045 | Incident Responder | Diagnose and resolve a blocking chain in < 5 minutes | 500 XP |

### 6.5 Scoring & Health Metrics

| ID | Requirement |
|---|---|
| GF-050 | Each database has a "Health Score" (0-100) based on: index health, vacuum status, capacity headroom, query performance |
| GF-051 | Health Score degrades over time without proactive checks (incentivizes regular engagement) |
| GF-052 | Team aggregate Health Score visible on dashboard |
| GF-053 | Alerts when Health Score drops below threshold trigger quest availability |

---

## 7. Strands Agent Implementation

### 7.1 Agent Structure

```python
from strands import Agent, tool
from strands.models import BedrockModel

# Initialize with Bedrock Claude
model = BedrockModel(model_id="us.anthropic.claude-sonnet-4-6-v1")

# Create the DB Ops agent
db_ops_agent = Agent(
    model=model,
    tools=[
        schema_tools,
        performance_tools,
        index_tools,
        maintenance_tools,
        gamification_tools,
    ],
    system_prompt=DBOPS_SYSTEM_PROMPT,
    hooks=[
        Tier3ApprovalHook(approvals=payload.get("approvals"), user_id=user_id),
        audit_hook,
        gamification_hook,
    ],
    conversation_manager=SlidingWindowManager(window_size=50),
)
```

### 7.2 Tool Definition Pattern

```python
from strands import tool

@tool
def get_slow_queries(db_identifier: str, engine: str, top_n: int = 10) -> dict:
    """Retrieve the top N slowest queries from the specified database.
    
    Args:
        db_identifier: The database identifier from the registry
        engine: Database engine type (aurora-postgresql, aurora-mysql, sqlserver, etc.)
        top_n: Number of slow queries to return (default 10)
    """
    adapter = get_adapter(engine)
    connection = get_connection(db_identifier)
    results = adapter.slow_queries(connection, top_n)
    
    # Award XP via gamification hook (handled automatically)
    return {"queries": results, "db": db_identifier, "engine": engine}


@tool
def create_index(db_identifier: str, table_name: str, columns: list[str], 
                 index_name: str, concurrently: bool = True) -> dict:
    """Create an index on the specified table. Requires approval.
    
    Args:
        db_identifier: Target database
        table_name: Table to index
        columns: List of columns to include in the index
        index_name: Name for the new index
        concurrently: Whether to create without locking (default True)
    """
    # Safety hook will intercept and request approval before execution
    adapter = get_adapter_from_registry(db_identifier)
    connection = get_privileged_connection(db_identifier)
    
    # This can run for hours on AgentCore — no timeout concern
    result = adapter.create_index(connection, table_name, columns, 
                                   index_name, concurrently)
    return {"status": "completed", "index": index_name, "result": result}
```

### 7.3 Safety Hooks

The Tier-3 gate is implemented in `src/hooks/tier3_approval.py` as a Strands
`HookProvider` on the `BeforeToolCallEvent` bus. It halts the agent loop with an
**interrupt** before a mutating tool runs and resumes only when the caller supplies
an `APPLY` decision bound to that operation's fingerprint. Because the callback runs
on the framework event bus rather than in the prompt, the model cannot suppress it —
a system-prompt rule alone would not be a security control.

Classification is a **fail-closed allowlist**: only verified read-only tools pass
ungated (`READ_ONLY_TOOLS` in `src/hooks/tier3_gate.py`), so any new or unrecognized
tool requires approval by default.

```python
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from src.hooks.tier3_gate import (
    APPLY, INTERRUPT_NAME, approval_request, find_decision, requires_approval,
)


class Tier3ApprovalHook(HookProvider):
    """Require an explicit operator APPLY before any Tier-3 tool executes."""

    def __init__(self, approvals=None, user_id="anonymous"):
        self._approvals = parse_approvals(approvals)  # from the invocation payload
        self._user_id = user_id

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self.gate_tier3)

    def gate_tier3(self, event: BeforeToolCallEvent) -> None:
        tool_name = event.tool_use["name"]
        if not requires_approval(tool_name):
            return  # Tier 1/2 read-only tool.

        tool_input = event.tool_use.get("input") or {}

        # No decision yet -> raises an interrupt and stops the loop before the
        # tool runs. On the follow-up invocation the operator's decision is
        # supplied preemptively, so this returns it instead of interrupting.
        response = event.interrupt(
            INTERRUPT_NAME,
            reason=approval_request(tool_name, tool_input),
            response=find_decision(self._approvals, tool_name, tool_input),
        )

        if not isinstance(response, str) or response.strip().upper() != APPLY:
            event.cancel_tool = f"Operation '{tool_name}' was not approved."
```

Approvals are matched on a SHA-256 fingerprint over the tool name **and** its
arguments, so an `APPLY` cannot be replayed against a different operation or the
same tool with different arguments. Beneath this gate,
`src/admin_ops/db/sql_guard.py` refuses constructs that leave the database entirely
(host command execution, filesystem access, outbound network calls, engine
reconfiguration); those are never approvable.

Legacy hook sketches below describe the original design intent and are retained for
context on audit/gamification only.


class AuditHook(Hook):
    """Log every tool execution for compliance."""
    
    def after_tool_call(self, tool_name, tool_input, tool_output, agent):
        log_to_cloudwatch({
            "timestamp": datetime.utcnow().isoformat(),
            "user": agent.session.user_id,
            "tool": tool_name,
            "input": sanitize(tool_input),
            "output_summary": summarize(tool_output),
            "session_id": agent.session.session_id,
        })
```

### 7.4 Gamification Hook

```python
class GamificationHook(Hook):
    """Award XP and check achievements after each operation."""
    
    def after_tool_call(self, tool_name, tool_input, tool_output, agent):
        user_id = agent.session.user_id
        tier = get_tool_tier(tool_name)
        
        # Award XP
        xp_earned = {1: 10, 2: 25, 3: 50}.get(tier, 5)
        
        # Bonus XP for proactive checks (no active alarm)
        if is_proactive_check(tool_name, tool_input):
            xp_earned *= 2
        
        update_user_xp(user_id, xp_earned)
        
        # Check achievements
        new_badges = check_achievements(user_id, tool_name, tool_input, tool_output)
        if new_badges:
            agent.add_to_response(
                f"🏅 Achievement unlocked: {', '.join(new_badges)}!"
            )
        
        # Update database health score
        update_health_score(tool_input.get("db_identifier"), tool_name)
```

### 7.5 MCP Integration (Optional — External Tools)

```python
from strands import Agent, MCPServer

# Connect to existing monitoring MCP servers
grafana_mcp = MCPServer("grafana-mcp", command="npx grafana-mcp-server")
pagerduty_mcp = MCPServer("pagerduty-mcp", command="npx pagerduty-mcp-server")

db_ops_agent = Agent(
    model=model,
    tools=[...],
    mcp_servers=[grafana_mcp, pagerduty_mcp],  # Agent discovers tools dynamically
)
```

---

## 8. Non-Functional Requirements

### 8.1 Security

| ID | Requirement |
|---|---|
| NFR-001 | All database credentials stored in AWS Secrets Manager |
| NFR-002 | Tier 1 & 2 operations use read-only database credentials |
| NFR-003 | Tier 3 operations use separate privileged credentials, invoked only after approval |
| NFR-004 | AgentCore Runtime sessions run in VPC with no public internet access |
| NFR-005 | Security groups restrict agent → database connectivity to required ports only |
| NFR-006 | All agent actions logged with user identity, timestamp, and full query text |
| NFR-007 | AgentCore Policy Engine (Cedar) enforces runtime boundaries on destructive operations |
| NFR-008 | IAM least-privilege for all service roles |
| NFR-009 | Session isolation prevents data leakage between concurrent users |

### 8.2 Reliability

| ID | Requirement |
|---|---|
| NFR-010 | Agent operations must not impact production database performance (statement timeouts enforced) |
| NFR-011 | Read-only queries enforce 30-second statement timeout at DB level |
| NFR-012 | Circuit breaker pattern if a database is unresponsive |
| NFR-013 | Graceful degradation if CloudWatch/Performance Insights unavailable |
| NFR-014 | AgentCore Runtime auto-recovers from transient failures within a session |
| NFR-015 | Long-running Tier 3 operations stream progress to user (no silent hanging) |

### 8.3 Scalability

| ID | Requirement |
|---|---|
| NFR-020 | Support up to 50 managed database instances |
| NFR-021 | Handle concurrent users (up to 50 simultaneous sessions via AgentCore) |
| NFR-022 | Database registry supports dynamic add/remove without redeployment |
| NFR-023 | Hot-reload tools without restarting the agent (Strands hot-reload feature) |

### 8.4 Observability

| ID | Requirement |
|---|---|
| NFR-030 | All agent invocations logged to CloudWatch Logs via AgentCore monitoring |
| NFR-031 | Token usage, latency, and success rates tracked per session |
| NFR-032 | Dashboard showing agent usage, gamification metrics, and error rates |
| NFR-033 | Alerting on agent failures or unusual activity patterns |

### 8.5 Compliance & Audit

| ID | Requirement |
|---|---|
| NFR-040 | Full audit trail of every query executed by the agent |
| NFR-041 | Tier 3 actions require recorded approval (who approved, when) |
| NFR-042 | Audit logs retained for 90 days minimum |
| NFR-043 | No PII or sensitive data stored in agent conversation history |

#### Customer responsibility for regulated data

The requirements above describe what this sample implements. They do not, and
cannot, establish compliance for a deployment.

The registry schema in §14 shows a database tagged `["critical", "pci"]`, and the
replication workflow can copy tables whose columns are named `card_number`,
`cvv`, `ssn`, `email`, and `phone`. Those are illustrative, but they reflect the
intended use: this sample is designed to be pointed at databases that may hold
regulated data. When it is, the following remain the deploying customer's
responsibility under the
[AWS shared responsibility model](https://aws.amazon.com/compliance/shared-responsibility-model/):

- **Scope.** Bringing an environment into PCI DSS scope by copying cardholder
  data into it, including any lower environment created by the replication
  tools. AWS's own PCI DSS attestation covers the services, not the customer's
  configuration or data — see
  [AWS PCI DSS compliance](https://aws.amazon.com/compliance/pci-dss-level-1-faqs/).
- **Segmentation and access control.** Network segmentation between scoped and
  unscoped environments, and least-privilege database grants. The sample's IAM
  and security-group configuration is a starting point sized for a demo.
- **Audit retention.** NFR-042 states a 90-day minimum, which is this sample's
  default and is *not* a compliance determination. PCI DSS, HIPAA, and various
  privacy regimes impose their own retention and protection requirements, and the
  operator log described in §8.4 can contain submitted SQL and bound values, so it
  inherits the sensitivity of the data it touches.
- **Masking is not anonymisation.** The masking tools are a development
  convenience. `partial` preserves leading and trailing characters, and `hash` is
  deterministic and unsalted, so values remain linkable. Neither satisfies
  HIPAA, PCI DSS, or GDPR de-identification requirements on its own, and the
  masked view leaves the base table readable to any role not explicitly revoked.
- **Lawful basis and data subject rights.** Where personal data is in scope,
  GDPR, CCPA, and equivalent regimes impose obligations — lawful basis, minimisation,
  and data subject rights — that no part of this sample addresses.

Per NFR-043 and A-01/A-03 of the threat model, this sample is intended for
non-production use with synthetic data. Using it against databases holding
regulated data is a decision that requires the controls above to be established
independently.

---

## 9. Architecture Components

| Component | Service | Purpose |
|---|---|---|
| Agent Framework | Strands Agents SDK (Python) | Agent logic, tool orchestration, hooks, steering |
| Runtime | Amazon Bedrock AgentCore Runtime | Managed execution (up to 8 hrs), session isolation, pay-per-use |
| Model | Amazon Bedrock (Claude) | LLM reasoning, natural language understanding |
| Policy | AgentCore Policy Engine (Cedar) | Runtime guardrails — block destructive ops by policy |
| Memory | AgentCore Memory Service | Cross-session context, cumulative knowledge |
| Gateway | AgentCore Gateway | Expose APIs/MCP servers as agent-compatible tools |
| Secrets | AWS Secrets Manager | Database credentials per instance |
| Registry | Amazon DynamoDB | Fleet inventory (database endpoints, engines, metadata) |
| Gamification Store | Amazon DynamoDB | XP, levels, badges, leaderboards, health scores |
| Monitoring | Amazon CloudWatch, Performance Insights | Shared metrics layer across all engines |
| Notifications | Amazon SNS → Slack/Teams | Achievements, approval requests, alerts |
| Audit | CloudWatch Logs, S3 (long-term) | Action audit trail |
| Dashboard | Amazon QuickSight or custom UI | Leaderboards, health scores, agent activity |

---

## 10. AgentCore Memory — Inter-Step & Cross-Session State

### 10.1 Why Memory Is Needed

The agent performs multi-step investigations where each step's output informs the next. Without memory:
- Step 3 can't reference what Step 1 found
- A follow-up session can't recall yesterday's diagnosis
- The agent re-queries information it already discovered

AgentCore Memory Service provides **short-term (within session)** and **long-term (across sessions)** persistence.

### 10.2 Memory Types

| Type | Scope | TTL | Purpose |
|---|---|---|---|
| **Working Memory** | Within a single session | Session duration (up to 8 hrs) | Pass findings between steps in a multi-step investigation |
| **Session Memory** | Persists after session ends | 7 days | Resume interrupted investigations, follow-up questions |
| **Semantic Memory** | Permanent (until deleted) | Indefinite | Learned patterns: "this DB tends to bloat on Mondays", "this team prefers online index builds" |
| **Episodic Memory** | Per-database history | 90 days | Past incidents, prior recommendations, what was tried before |

### 10.3 Working Memory — Between Steps

When the agent executes a multi-step plan, each step stores its output in working memory for subsequent steps to reference.

```python
@tool
def get_slow_queries(db_identifier: str, top_n: int = 10) -> dict:
    """Get slow queries and store in working memory for next steps."""
    results = adapter.slow_queries(connection, top_n)
    
    # Store in working memory — available to subsequent steps
    memory.working.store(
        key=f"slow_queries_{db_identifier}",
        value=results,
        context="Top slow queries identified for further analysis"
    )
    return results


@tool
def get_execution_plan(db_identifier: str, query_id: str) -> dict:
    """Analyze execution plan for a query found in a previous step."""
    
    # Retrieve from working memory — uses output of prior step
    slow_queries = memory.working.get(f"slow_queries_{db_identifier}")
    target_query = find_query_by_id(slow_queries, query_id)
    
    plan = adapter.explain(connection, target_query["sql"])
    
    # Store plan for recommendation step
    memory.working.store(
        key=f"exec_plan_{query_id}",
        value=plan,
        context="Execution plan showing sequential scan — candidate for index"
    )
    return plan


@tool
def recommend_index(db_identifier: str, query_id: str) -> dict:
    """Generate index recommendation based on prior analysis steps."""
    
    # Pull everything from working memory — no re-querying needed
    slow_query = memory.working.get(f"slow_queries_{db_identifier}")
    exec_plan = memory.working.get(f"exec_plan_{query_id}")
    
    # Agent uses all prior context to generate recommendation
    recommendation = generate_index_recommendation(slow_query, exec_plan)
    return recommendation
```

### 10.4 Session Memory — Resume & Follow-Up

```python
# End of session — agent summarizes and stores
memory.session.store(
    session_id="sess-84721",
    summary={
        "database": "prod-orders-pg",
        "findings": [
            "Missing index on orders.customer_id causing 45s queries",
            "3 long-running sessions from batch job (expected)",
            "Vacuum running 6 hours behind on orders table"
        ],
        "actions_taken": [
            "Created index idx_orders_customer_id (approved by @dba-lead)"
        ],
        "pending": [
            "Vacuum still behind — monitor tomorrow",
            "Batch job optimization — user deferred to next week"
        ],
        "timestamp": "2026-05-11T09:25:00Z"
    }
)

# Next day — user returns
# User: "What was pending from yesterday on prod-orders?"
# Agent retrieves session memory automatically
previous = memory.session.get_recent(
    database="prod-orders-pg",
    user="ganesrar",
    lookback_days=7
)
# Agent responds with context from prior session
```

### 10.5 Semantic Memory — Learned Patterns

The agent accumulates knowledge about databases and team preferences over time.

```python
# Agent learns patterns from repeated observations
memory.semantic.store(
    entity="prod-orders-pg",
    knowledge=[
        {
            "pattern": "Table bloat increases every Monday due to weekend batch ingestion",
            "confidence": 0.9,
            "learned_from": ["sess-84721", "sess-83102", "sess-81456"],
            "recommendation": "Schedule VACUUM for Monday 6 AM"
        },
        {
            "pattern": "Index fragmentation on orders table exceeds 30% every 2 weeks",
            "confidence": 0.85,
            "learned_from": ["sess-84100", "sess-82200"],
            "recommendation": "Proactive REINDEX bi-weekly"
        }
    ]
)

# Agent learns team preferences
memory.semantic.store(
    entity="team:orders-team",
    knowledge=[
        {
            "preference": "Always use CONCURRENTLY for index operations in production",
            "source": "Rejection of non-concurrent index in sess-82200"
        },
        {
            "preference": "Prefer off-hours (after 10 PM EST) for Tier 3 maintenance",
            "source": "User feedback in sess-83500"
        }
    ]
)
```

### 10.6 Episodic Memory — Incident History

```python
# After each investigation, store as an episode
memory.episodic.store(
    database="prod-orders-pg",
    episode={
        "type": "performance_incident",
        "date": "2026-05-11",
        "trigger": "User reported slow queries",
        "root_cause": "Missing index on orders.customer_id",
        "resolution": "Created index CONCURRENTLY",
        "impact": "Query time reduced from 45s to 0.3s",
        "time_to_resolve": "4m 51s",
        "session_id": "sess-84721",
        "user": "ganesrar"
    }
)

# Future investigation — agent checks history first
# User: "prod-orders is slow again"
# Agent retrieves episodic memory
past_incidents = memory.episodic.get(
    database="prod-orders-pg",
    type="performance_incident",
    lookback_days=90
)
# Agent: "Last time this happened (May 11), it was a missing index. 
#          Let me check if a similar pattern is occurring..."
```

### 10.7 Memory Flow in Multi-Step Execution

```
Step 1: get_active_sessions
   └─ Stores → working_memory["active_sessions_prod-orders-pg"]

Step 2: get_slow_queries
   └─ Reads ← working_memory["active_sessions_prod-orders-pg"] (correlates sessions to queries)
   └─ Stores → working_memory["slow_queries_prod-orders-pg"]

Step 3: get_wait_events
   └─ Reads ← working_memory["slow_queries_prod-orders-pg"] (checks if slow queries are waiting)
   └─ Stores → working_memory["wait_events_prod-orders-pg"]

Step 4: get_execution_plan
   └─ Reads ← working_memory["slow_queries_prod-orders-pg"] (picks worst query)
   └─ Stores → working_memory["exec_plan_query-123"]

Step 5: recommend_index
   └─ Reads ← working_memory["slow_queries_*", "exec_plan_*", "wait_events_*"]
   └─ Reads ← semantic_memory["prod-orders-pg"] (team prefers CONCURRENTLY)
   └─ Reads ← episodic_memory["prod-orders-pg"] (was this tried before?)
   └─ Generates recommendation with full context

Step 6: create_index (after approval)
   └─ Reads ← working_memory["recommended_index"]
   └─ Executes
   └─ Stores → episodic_memory (new episode: what was done and result)
   └─ Stores → session_memory (summary for follow-up)
```

### 10.8 Memory Requirements

| ID | Requirement |
|---|---|
| MEM-001 | Working memory persists all tool outputs within a session for inter-step reference |
| MEM-002 | Agent MUST reference prior step outputs from memory (not re-query the database) |
| MEM-003 | Session memory stores a summary at end of each session (findings, actions, pending items) |
| MEM-004 | Session memory retrievable for 7 days to support follow-up conversations |
| MEM-005 | Semantic memory accumulates learned patterns (auto-detected after 3+ similar observations) |
| MEM-006 | Episodic memory stores every investigation as a structured episode (90-day retention) |
| MEM-007 | Agent checks episodic memory at start of investigation ("has this happened before?") |
| MEM-008 | Agent checks semantic memory before recommendations ("does this team have preferences?") |
| MEM-009 | Memory is scoped per-database and per-team (no cross-tenant leakage) |
| MEM-010 | Users can view, edit, or delete semantic/episodic memories via UI ("Agent learned" panel) |
| MEM-011 | Memory content excluded from audit logs if it contains query text with sensitive data |
| MEM-012 | Working memory cleared automatically when session ends |

### 10.9 UI — "Agent Memory" Panel

```
┌─── AGENT MEMORY (prod-orders-pg) ────────────────────────────────────────┐
│                                                                           │
│  📝 Learned Patterns (Semantic)                                          │
│  ├─ "Bloat increases every Monday — recommend VACUUM Mon 6 AM"    [Edit] │
│  ├─ "Index fragmentation hits 30% bi-weekly"                      [Edit] │
│  └─ "Team prefers CONCURRENTLY + off-hours for maintenance"       [Edit] │
│                                                                           │
│  📖 Past Incidents (Episodic)                                            │
│  ├─ May 11: Missing index on customer_id → resolved (4m 51s)     [View] │
│  ├─ May 03: Vacuum 12hrs behind → manual VACUUM triggered        [View] │
│  └─ Apr 28: Blocking chain from batch job → killed session        [View] │
│                                                                           │
│  💬 Recent Sessions                                                      │
│  ├─ Today: "Why is prod-orders slow?" → index created             [Resume]│
│  └─ Yesterday: "Check capacity" → 6 months headroom              [Resume]│
│                                                                           │
│  ┌────────────────┐                                                       │
│  │ 🗑️ Clear Memory │ (requires confirmation)                              │
│  └────────────────┘                                                       │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Agent Traceability & Execution Flow

### 11.1 Trace Model

Every agent interaction produces a **trace** — a step-by-step record of what the agent thought, planned, and executed. Traces are visible to the user in real-time and stored for audit.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ TRACE ID: trc-20260511-a3f9c                                            │
│ User: ganesrar | Session: sess-84721 | Started: 2026-05-11T09:15:03Z   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│ Step 1: INTENT RECOGNITION                                              │
│ ├─ User input: "Why is prod-orders slow today?"                        │
│ ├─ Identified: performance diagnosis                                    │
│ ├─ Target DB: prod-orders-pg (aurora-postgresql)                        │
│ └─ [✓ Acknowledged by user — "Proceed" button clicked]                 │
│                                                                         │
│ Step 2: PLAN GENERATION                                                 │
│ ├─ Plan: 1) Check active sessions 2) Query pg_stat_statements          │
│ │         3) Check wait events 4) Check locks                           │
│ ├─ Estimated steps: 4                                                   │
│ ├─ Tier: 1 (read-only)                                                 │
│ └─ [✓ Plan approved — "Execute Plan" button clicked]                   │
│                                                                         │
│ Step 3: TOOL EXECUTION — get_active_sessions                            │
│ ├─ Input: {db_identifier: "prod-orders-pg"}                            │
│ ├─ Query: SELECT * FROM pg_stat_activity WHERE state = 'active'        │
│ ├─ Duration: 0.8s                                                       │
│ ├─ Result: 23 active sessions (3 long-running)                          │
│ └─ [✓ Continue — "Next Step" button clicked]                           │
│                                                                         │
│ Step 4: TOOL EXECUTION — get_slow_queries                               │
│ ├─ Input: {db_identifier: "prod-orders-pg", top_n: 10}                 │
│ ├─ Query: SELECT ... FROM pg_stat_statements ORDER BY total_exec_time  │
│ ├─ Duration: 1.2s                                                       │
│ ├─ Result: Top query taking 45s avg (sequential scan on orders table)  │
│ └─ [✓ Continue — "Next Step" button clicked]                           │
│                                                                         │
│ Step 5: ANALYSIS & RECOMMENDATION                                       │
│ ├─ Finding: Missing index on orders.customer_id                         │
│ ├─ Recommendation: CREATE INDEX CONCURRENTLY idx_orders_customer_id...  │
│ ├─ Estimated impact: 85% reduction in query time                        │
│ ├─ Tier escalation: Tier 2 (advisory) → Tier 3 (if user wants action) │
│ └─ [🎮 +25 XP awarded | 🔍 Progress: 4250 → 4275 XP]                 │
│                                                                         │
│ Step 6: USER DECISION POINT                                             │
│ ├─ Options presented:                                                   │
│ │   [📋 Save Recommendation] [⚡ Execute Now] [❌ Dismiss]              │
│ ├─ User clicked: "Execute Now"                                         │
│ ├─ Tier 3 triggered → Approval request sent                            │
│ └─ [⏳ Awaiting approval from: dba-team]                               │
│                                                                         │
│ Step 7: APPROVAL GATE                                                   │
│ ├─ Approver: @dba-lead                                                 │
│ ├─ Approved at: 2026-05-11T09:18:42Z                                   │
│ ├─ [✓ Approved — "Confirm Execution" button clicked by approver]       │
│ └─ Cedar policy check: PASSED                                          │
│                                                                         │
│ Step 8: TIER 3 EXECUTION — create_index                                 │
│ ├─ SQL: CREATE INDEX CONCURRENTLY idx_orders_customer_id ON orders(...) │
│ ├─ Progress: ████████████░░░░ 75% (streaming)                          │
│ ├─ Duration: 3m 42s                                                     │
│ ├─ Result: Index created successfully                                   │
│ └─ [🎮 +50 XP | 🏅 Achievement: ⚡ Speed Demon unlocked!]             │
│                                                                         │
│ Step 9: VERIFICATION                                                    │
│ ├─ Re-ran slow query analysis                                          │
│ ├─ Query time: 45s → 0.3s (99.3% improvement)                         │
│ ├─ [✓ User acknowledged — "Complete" button clicked]                   │
│ └─ [🎮 +10 XP bonus for verification]                                 │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│ TRACE COMPLETE | Total XP earned: 85 | Duration: 4m 51s | Steps: 9     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 11.2 Trace Requirements

| ID | Requirement |
|---|---|
| TR-001 | Every agent interaction generates a unique trace ID |
| TR-002 | Each step in the trace records: tool name, input, output, duration, and user action |
| TR-003 | Traces are visible to the user in real-time (streaming UI) |
| TR-004 | Traces are stored in CloudWatch Logs and S3 for audit (90-day retention) |
| TR-005 | Traces are searchable by user, database, tool, date range, and trace ID |
| TR-006 | Failed steps show error details and agent's recovery action |
| TR-007 | Each trace step shows the Cedar policy evaluation result (if applicable) |
| TR-008 | Trace replay: any historical trace can be replayed in the UI for review |

---

## 12. Human-in-the-Loop (HITL) — Button-Click Approval at Every Step

### 12.1 HITL Philosophy

**Nothing executes without explicit user acknowledgment.** The agent proposes, the human disposes. Every step requires a button click before the agent proceeds.

### 12.2 Interaction Modes

| Mode | Behavior | Use Case |
|---|---|---|
| **Step-by-Step** (default) | User clicks "Next" after each step | Learning, sensitive systems, new users |
| **Plan-Approve** | User approves the full plan, then agent executes all steps | Experienced users, Tier 1 operations |
| **Auto-Read / Manual-Write** | Tier 1 auto-proceeds; Tier 2/3 require clicks | Balanced mode for daily use |

User selects their preferred mode in settings. Can override per-session.

### 12.3 Button Actions at Each Step

```
┌─────────────────────────────────────────────────────────────────┐
│ STEP: Agent identified 3 long-running queries on prod-orders-pg │
│                                                                 │
│ Agent wants to: Analyze query execution plans                   │
│ Tool: get_execution_plan                                        │
│ Target: prod-orders-pg                                          │
│ Tier: 1 (read-only)                                            │
│                                                                 │
│ ┌───────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────┐  │
│ │ ▶ Proceed │  │ ✏️ Modify  │  │ ⏭ Skip  │  │ ⏹ Stop Agent│  │
│ └───────────┘  └───────────┘  └──────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

| Button | Action | Available At |
|---|---|---|
| **▶ Proceed** | Approve this step, agent executes and moves to next | Every step |
| **✏️ Modify** | Edit the agent's proposed action (change parameters, target DB, etc.) | Every step |
| **⏭ Skip** | Skip this step, move to next in the plan | Every step |
| **⏹ Stop Agent** | Halt execution entirely, end session | Every step |
| **📋 Save Recommendation** | Save finding without executing (Tier 2 → bookmark) | Recommendation steps |
| **⚡ Execute Now** | Escalate to Tier 3, trigger approval workflow | Recommendation steps |
| **✓ Approve** | Approver grants permission for Tier 3 action | Approval gates only |
| **✗ Reject** | Approver denies the action with optional reason | Approval gates only |
| **🔄 Re-run** | Re-execute the previous step (e.g., after conditions change) | Post-execution |

### 12.4 HITL Requirements

| ID | Requirement |
|---|---|
| HITL-001 | Agent MUST pause and present proposed action before executing ANY tool |
| HITL-002 | Each pause presents: tool name, input parameters, target database, tier level, and risk assessment |
| HITL-003 | User must click an action button to proceed — no auto-advance (except in Plan-Approve mode for Tier 1) |
| HITL-004 | "Modify" button opens parameter editor — user can change inputs before execution |
| HITL-005 | "Stop Agent" immediately halts all execution and rolls back any in-progress operations where possible |
| HITL-006 | Tier 3 actions require TWO approvals: user click + designated approver click |
| HITL-007 | Approval requests sent via Slack/Teams with embedded approve/reject buttons |
| HITL-008 | Approval timeout: 30 minutes. If no response, action is cancelled (not auto-approved) |
| HITL-009 | All button clicks are logged in the trace (who, what, when) |
| HITL-010 | Session idle timeout: if no button click for 15 minutes, agent pauses and notifies user |
| HITL-011 | Keyboard shortcuts available for power users (Enter = Proceed, Esc = Stop, S = Skip) |

### 12.5 Approval Flow for Tier 3

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
│  User    │     │   Agent      │     │  Slack/Teams │     │  Approver  │
│  (UI)    │     │  (AgentCore) │     │  Notification│     │  (DBA)     │
└────┬─────┘     └──────┬───────┘     └──────┬───────┘     └─────┬──────┘
     │                   │                    │                    │
     │ Click "Execute"   │                    │                    │
     │──────────────────▶│                    │                    │
     │                   │                    │                    │
     │                   │ Send approval req  │                    │
     │                   │───────────────────▶│                    │
     │                   │                    │                    │
     │                   │                    │ Notify with buttons│
     │                   │                    │───────────────────▶│
     │                   │                    │                    │
     │  Show "Awaiting   │                    │                    │
     │◀──approval..."────│                    │                    │
     │                   │                    │                    │
     │                   │                    │  Click "Approve"   │
     │                   │                    │◀───────────────────│
     │                   │                    │                    │
     │                   │ Approval received  │                    │
     │                   │◀───────────────────│                    │
     │                   │                    │                    │
     │                   │ Cedar policy check │                    │
     │                   │─────────┐          │                    │
     │                   │◀────────┘          │                    │
     │                   │                    │                    │
     │  Show "Executing  │                    │                    │
     │◀──with progress"──│                    │                    │
     │                   │                    │                    │
     │  ████░░ 60%       │                    │                    │
     │◀──streaming───────│                    │                    │
     │                   │                    │                    │
     │  "Complete" +XP   │                    │                    │
     │◀──────────────────│                    │                    │
     │                   │                    │                    │
     │ Click "Acknowledge"                    │                    │
     │──────────────────▶│                    │                    │
```

---

## 13. Gamified UI — User Interaction Design

### 12.1 Main Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  🎮 DB OPS COMMAND CENTER                          ganesrar | Lv.4 Senior DBA│
│  ═══════════════════════════════════════════════════════════════════════════ │
│                                                                             │
│  ┌─── YOUR STATS ───────────────────┐  ┌─── ACTIVE QUESTS ──────────────┐ │
│  │ XP: 4,275 / 5,000 ████████░░ 85% │  │ 📋 Daily Health Check    50 XP │ │
│  │ Level: Senior DBA                 │  │    [2/5 databases checked]     │ │
│  │ Streak: 🔥 12 days               │  │ 📋 Index Audit          200 XP │ │
│  │ Weekly XP: 475 (Rank #3)         │  │    [0/3 databases audited]     │ │
│  │ Badges: 🔍⚡🏥🌍 (4/11)          │  │ 📋 Bloat Buster         250 XP │ │
│  └───────────────────────────────────┘  │    [1/2 PG databases]          │ │
│                                         └────────────────────────────────┘ │
│  ┌─── DATABASE FLEET ──────────────────────────────────────────────────┐   │
│  │ Database              │ Engine     │ Health │ Last Check │ Status   │   │
│  │───────────────────────┼────────────┼────────┼────────────┼──────────│   │
│  │ prod-orders-pg        │ Aurora PG  │ 87/100 │ 2h ago     │ 🟢 OK   │   │
│  │ prod-sessions-redis   │ ElastiCache│ 92/100 │ 1h ago     │ 🟢 OK   │   │
│  │ prod-events-ddb       │ DynamoDB   │ 74/100 │ 6h ago     │ 🟡 WARN │   │
│  │ prod-analytics-rs     │ Redshift   │ 61/100 │ 1d ago     │ 🔴 STALE│   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─── AGENT CHAT ──────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  You: Why is prod-orders slow?                                      │   │
│  │                                                                      │   │
│  │  Agent: I'll investigate prod-orders-pg. Here's my plan:            │   │
│  │  ┌────────────────────────────────────────────────────────────┐     │   │
│  │  │ 1. Check active sessions          [Tier 1 - Read]         │     │   │
│  │  │ 2. Analyze slow queries           [Tier 1 - Read]         │     │   │
│  │  │ 3. Check wait events              [Tier 1 - Read]         │     │   │
│  │  │ 4. Review execution plans         [Tier 1 - Read]         │     │   │
│  │  └────────────────────────────────────────────────────────────┘     │   │
│  │                                                                      │   │
│  │  ┌───────────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │   │
│  │  │ ▶ Execute Plan│  │ ✏️ Modify │  │ ⏹ Cancel │  │ 💬 Ask More   │  │   │
│  │  └───────────────┘  └──────────┘  └──────────┘  └───────────────┘  │   │
│  │                                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─── TRACE PANEL (collapsible) ───────────────────────────────────────┐   │
│  │ ● Step 1: get_active_sessions ✓ (0.8s)                    [Expand] │   │
│  │ ● Step 2: get_slow_queries ✓ (1.2s)                       [Expand] │   │
│  │ ◐ Step 3: get_wait_events — executing...                           │   │
│  │ ○ Step 4: get_execution_plans — pending                            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─── LEADERBOARD ─────────────┐  ┌─── RECENT ACHIEVEMENTS ───────────┐   │
│  │ This Week                    │  │ 🏅 ⚡ Speed Demon — 2h ago        │   │
│  │ 🥇 alice    — 820 XP        │  │ 🏅 🌍 Polyglot   — yesterday     │   │
│  │ 🥈 bob      — 650 XP        │  │ 🏅 🔍 First Blood — 3 days ago   │   │
│  │ 🥉 ganesrar — 475 XP        │  │                                   │   │
│  └──────────────────────────────┘  └───────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 12.2 Step Execution View (Human-in-the-Loop)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 3 of 4                                           Trace: trc-a3f9c     │
│  ═══════════════════════════════════════════════════════════════════════════ │
│                                                                             │
│  ┌─── PROPOSED ACTION ─────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  Tool: get_wait_events                                              │   │
│  │  Target: prod-orders-pg (Aurora PostgreSQL 15.4)                    │   │
│  │  Tier: 1 (Read-Only) 🟢                                            │   │
│  │  Risk: None — read-only system view query                           │   │
│  │                                                                      │   │
│  │  SQL to execute:                                                     │   │
│  │  ┌────────────────────────────────────────────────────────────────┐ │   │
│  │  │ SELECT wait_event_type, wait_event, COUNT(*),                  │ │   │
│  │  │        SUM(EXTRACT(EPOCH FROM (now() - query_start)))          │ │   │
│  │  │ FROM pg_stat_activity                                          │ │   │
│  │  │ WHERE state != 'idle' AND wait_event IS NOT NULL               │ │   │
│  │  │ GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20;                       │ │   │
│  │  └────────────────────────────────────────────────────────────────┘ │   │
│  │                                                                      │   │
│  │  Statement timeout: 30s                                             │   │
│  │  Credentials: dbops_readonly (read-only)                            │   │
│  │                                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌───────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────┐             │
│  │ ▶ Proceed │  │ ✏️ Modify  │  │ ⏭ Skip  │  │ ⏹ Stop Agent│             │
│  │  (Enter)  │  │   (M)     │  │   (S)    │  │    (Esc)     │             │
│  └───────────┘  └───────────┘  └──────────┘  └──────────────┘             │
│                                                                             │
│  ┌─── CONTEXT ─────────────────────────────────────────────────────────┐   │
│  │ Why this step: Previous step found 3 long-running queries.          │   │
│  │ Agent wants to check if they're waiting on locks or I/O.            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 12.3 Tier 3 Approval View (Approver's Slack/Teams Message)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  🤖 DB Ops Agent — Approval Request                                         │
│  ═══════════════════════════════════════════════════════════════════════════ │
│                                                                             │
│  Requested by: ganesrar (Senior DBA)                                       │
│  Database: prod-orders-pg (Aurora PostgreSQL)                               │
│  Environment: 🔴 PRODUCTION                                                │
│                                                                             │
│  Action: CREATE INDEX                                                       │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │ CREATE INDEX CONCURRENTLY idx_orders_customer_id                   │     │
│  │ ON orders (customer_id)                                           │     │
│  │ -- Estimated time: 3-5 minutes                                    │     │
│  │ -- Table size: 45GB, 120M rows                                    │     │
│  │ -- Impact: non-blocking (CONCURRENTLY)                            │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  Justification: Query on orders.customer_id averaging 45s (seq scan).      │
│  Expected improvement: 99% reduction in query time.                        │
│                                                                             │
│  Cedar Policy: ✓ PASSED (production-index-creation allowed for dba-role)   │
│                                                                             │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────────┐        │
│  │ ✓ Approve    │  │ ✗ Reject         │  │ 💬 Request More Info   │        │
│  └──────────────┘  └──────────────────┘  └────────────────────────┘        │
│                                                                             │
│  ⏰ Expires in: 28 minutes                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 12.4 Progress Streaming View (Long-Running Tier 3)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  EXECUTING: CREATE INDEX on prod-orders-pg                    ⏱ 2m 14s      │
│  ═══════════════════════════════════════════════════════════════════════════ │
│                                                                             │
│  Progress: ████████████████████░░░░░░░░░░ 65%                              │
│                                                                             │
│  Phase: Scanning table (78M / 120M rows processed)                         │
│  Estimated remaining: ~1m 30s                                              │
│  Lock status: No exclusive locks held (CONCURRENTLY mode)                  │
│  Active sessions impacted: 0                                               │
│                                                                             │
│  Live metrics:                                                              │
│  ├─ CPU: 34% (normal)                                                      │
│  ├─ IOPS: 12,400 read (elevated, expected)                                │
│  └─ Connections: 24/100 (normal)                                           │
│                                                                             │
│  ┌──────────────────┐                                                       │
│  │ ⏹ Cancel & Rollback │                                                   │
│  └──────────────────┘                                                       │
│                                                                             │
│  ┌─── LIVE LOG ────────────────────────────────────────────────────────┐   │
│  │ 09:18:42 — Index creation started                                   │   │
│  │ 09:18:43 — Scanning table: orders (120M rows)                       │   │
│  │ 09:19:15 — 25% complete (30M rows)                                  │   │
│  │ 09:19:48 — 50% complete (60M rows)                                  │   │
│  │ 09:20:21 — 65% complete (78M rows)                                  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 12.5 Achievement Notification (In-Context)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ┌─── 🏅 ACHIEVEMENT UNLOCKED! ──────────────────────────────────────────┐ │
│  │                                                                        │ │
│  │  ⚡ SPEED DEMON                                                       │ │
│  │  "Optimize a query with > 50% improvement"                            │ │
│  │                                                                        │ │
│  │  Your result: 99.3% improvement (45s → 0.3s)                         │ │
│  │  +50 XP bonus                                                         │ │
│  │                                                                        │ │
│  │  Progress: 5/11 badges earned                                         │ │
│  │  Next badge hint: "Operate on 3+ engines in one session" 🌍           │ │
│  │                                                                        │ │
│  │  ┌─────────────┐  ┌─────────────┐                                    │ │
│  │  │ 🎉 Share    │  │ ▶ Continue  │                                    │ │
│  │  └─────────────┘  └─────────────┘                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 12.6 UI Requirements

| ID | Requirement |
|---|---|
| UI-001 | Web-based dashboard (React/Next.js) accessible via browser |
| UI-002 | Real-time WebSocket connection to AgentCore for streaming updates |
| UI-003 | Trace panel visible at all times (collapsible) showing step-by-step progress |
| UI-004 | Every step displays: tool, SQL/action, target DB, tier, risk level before execution |
| UI-005 | Action buttons (Proceed/Modify/Skip/Stop) are always visible and keyboard-accessible |
| UI-006 | Gamification elements (XP bar, achievements, streak) visible without scrolling |
| UI-007 | Leaderboard updates in real-time via WebSocket |
| UI-008 | Health Score per database shown with color coding (green/yellow/red) |
| UI-009 | Notification toast for achievements with animation |
| UI-010 | Dark mode and light mode support |
| UI-011 | Mobile-responsive for on-call approvals (approve/reject buttons work on mobile) |
| UI-012 | Slack/Teams integration for approval buttons (interactive messages) |
| UI-013 | Session history: browse and replay past traces |
| UI-014 | Export trace as PDF for incident reports |

---

## 14. Database Registry Schema

```json
{
  "db_identifier": "prod-orders-pg",
  "engine": "aurora-postgresql",
  "engine_version": "15.4",
  "endpoint": "prod-orders.cluster-xxx.us-east-1.rds.amazonaws.com",
  "port": 5432,
  "secret_arn": "arn:aws:secretsmanager:us-east-1:123456789:secret:prod-orders-creds",
  "privileged_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789:secret:prod-orders-admin",
  "environment": "production",
  "team_owner": "orders-team",
  "tier_3_approvers": ["dba-team", "orders-lead"],
  "tags": ["critical", "pci"],
  "health_score": 87,
  "last_checked": "2026-05-11T08:30:00Z"
}
```

---

## 15. Gamification Data Model

### User Profile

```json
{
  "user_id": "ganesrar",
  "display_name": "Ganesh",
  "level": 4,
  "level_name": "Senior DBA",
  "total_xp": 4250,
  "xp_to_next_level": 750,
  "badges": ["first_blood", "healer", "speed_demon", "polyglot"],
  "current_streak": 12,
  "longest_streak": 23,
  "team": "platform-team",
  "databases_managed": ["prod-orders-pg", "prod-sessions-redis", "prod-events-ddb"],
  "weekly_xp": 450,
  "monthly_rank": 3
}
```

### Leaderboard Entry

```json
{
  "period": "2026-W19",
  "rankings": [
    {"rank": 1, "user_id": "user-a", "xp": 820, "badges_earned": 2},
    {"rank": 2, "user_id": "user-b", "xp": 650, "badges_earned": 1},
    {"rank": 3, "user_id": "ganesrar", "xp": 450, "badges_earned": 1}
  ]
}
```

---

## 16. Phased Delivery

| Phase | Scope | Success Criteria |
|---|---|---|
| **Phase 1** | Strands agent + AgentCore deployment. Aurora PostgreSQL + DynamoDB, Tier 1 only. Basic XP system. | Agent answers "what's slow?" accurately. XP awarded per interaction. |
| **Phase 2** | Add MySQL, SQL Server. Add Tier 2 advisory. Achievements & badges. | Agent generates valid recommendations. Badges awarded correctly. |
| **Phase 3** | Add Redshift, ElastiCache. Tier 3 with Cedar policies + approval. Leaderboards. | End-to-end: diagnose → recommend → approve → execute (no timeout). Leaderboard visible. |
| **Phase 4** | Proactive mode: CloudWatch Alarm → Agent auto-investigates. Quests & seasonal challenges. | Agent posts findings to Slack within 2 min. Daily quests drive engagement. |
| **Phase 5** | MCP integration (Grafana, PagerDuty). Cross-team competitions. Health Score dashboards. | Full observability loop. Teams competing on DB health. |

---

## 17. Acceptance Criteria

- [ ] Agent deployed on AgentCore Runtime with no Lambda dependency
- [ ] Agent correctly identifies database engine from natural language
- [ ] Agent returns accurate performance data matching direct SQL query results
- [ ] Long-running operations (index creation, VACUUM) complete without timeout
- [ ] Real-time streaming of progress for Tier 3 operations
- [ ] Tier 3 operations blocked by Cedar policy when not approved
- [ ] XP awarded correctly per operation tier
- [ ] Achievements triggered on correct conditions
- [ ] Leaderboard updates in real-time
- [ ] Health Score reflects actual database state
- [ ] Audit log captures 100% of agent-executed queries
- [ ] No production database impact from agent read-only operations
- [ ] Hot-reload of new tools without redeployment
- [ ] Every agent step pauses for user button-click before executing
- [ ] Trace panel shows real-time step-by-step progress with expand/collapse
- [ ] Tier 3 approval buttons work in Slack/Teams (interactive messages)
- [ ] UI displays SQL/action to be executed BEFORE user approves each step
- [ ] "Stop Agent" button immediately halts execution at any point
- [ ] All button clicks recorded in trace with timestamp and user identity

---

## 18. Out of Scope (v1)

- Oracle on RDS
- Neptune (Graph DB)
- Timestream (Time Series)
- Cross-database joins or federated queries
- Automated remediation without human approval
- Cost optimization recommendations (separate initiative)
- Mobile app for gamification dashboard (web only for v1)

---

## 19. Dependencies

| Dependency | Owner | Status |
|---|---|---|
| AgentCore Runtime access (preview/GA) | AWS / Cloud team | Required |
| VPC connectivity (AgentCore → all target DBs) | Network team | Required |
| Read-only credentials per database | DBA team | Required |
| Privileged credentials per database (Tier 3) | DBA team | Required |
| Secrets Manager entries per database | DBA team | Required |
| Bedrock model access (Claude) | Cloud team | Required |
| Cedar policy definitions for Tier 3 ops | Security team | Required |
| Slack/Teams webhook for notifications | Platform team | Phase 3 |
| CloudWatch alarms on target databases | SRE team | Phase 4 |
| Grafana MCP server (optional) | Observability team | Phase 5 |

---

## 20. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| AgentCore Runtime availability (new service) | Cannot deploy | Fallback: deploy Strands agent on ECS Fargate (same code, different runtime) |
| 8-hour session cost for idle agents | Unexpected spend | Configure session idle timeout (e.g., 30 min inactive → terminate) |
| Strands SDK breaking changes (open-source) | Agent instability | Pin SDK version, test upgrades in staging |
| Cedar policy misconfiguration | Blocked legitimate ops or allowed dangerous ones | Policy-as-code in version control, test in staging |
| Gamification gaming (XP farming) | Meaningless leaderboards | Rate-limit XP per action per database per day |
