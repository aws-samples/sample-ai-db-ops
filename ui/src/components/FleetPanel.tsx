/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

"use client";

import CustomButtonsGroup from "@/components/admin/CustomButtonsGroup";
import type { Engine } from "@/components/admin/SqlEditorDrawer";

interface FleetPanelProps {
  selectedDb: string | null;
  onSelectDb: (db: string) => void;
  agentType: string;
  onCloneClick?: () => void;
  onQuickAction?: (prompt: string) => void;
}

const databases: Record<string, Array<{ id: string; name: string; env: string; health: number; lastCheck: string }>> = {
  postgresql: [
    { id: "database-test", name: "Aurora PG (database-test)", env: "production", health: 92, lastCheck: "2m ago" },
  ],
  mysql: [
    { id: "dbops-aurora-mysql", name: "Aurora MySQL (Prod)", env: "production", health: 95, lastCheck: "1m ago" },
  ],
  oracle: [
    { id: "oracle-prod", name: "Oracle EE 19c (Prod)", env: "production", health: 88, lastCheck: "5m ago" },
  ],
  dynamodb: [
    { id: "dbops-orders", name: "Orders", env: "production", health: 100, lastCheck: "1m ago" },
    { id: "dbops-registry", name: "DB Registry", env: "production", health: 100, lastCheck: "1m ago" },
    { id: "dbops-gamification", name: "Gamification", env: "production", health: 100, lastCheck: "1m ago" },
    { id: "dbops-leaderboard", name: "Leaderboard", env: "production", health: 100, lastCheck: "1m ago" },
  ],
};

function HealthBadge({ score }: { score: number }) {
  const color = score >= 80 ? "text-green-400" : score >= 60 ? "text-yellow-400" : "text-red-400";
  const icon = score >= 80 ? "🟢" : score >= 60 ? "🟡" : "🔴";
  return <span className={`text-xs font-medium ${color}`}>{icon} {score}</span>;
}

function EnvBadge({ env }: { env: string }) {
  const styles = env === "production"
    ? "bg-red-900/50 text-red-300 border-red-700"
    : "bg-green-900/50 text-green-300 border-green-700";
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${styles}`}>
      {env === "production" ? "PROD" : "DEV"}
    </span>
  );
}

interface ActionButtonProps {
  label: string;
  prompt: string;
  tooltip: string;
  accent: string;
  onClick: (prompt: string) => void;
}

function ActionButton({ label, prompt, tooltip, accent, onClick }: ActionButtonProps) {
  return (
    <button
      onClick={() => onClick(prompt)}
      data-tooltip={tooltip}
      className={`rounded-lg bg-slate-800 border border-slate-700 px-2 py-2 text-[11px] font-medium text-slate-300 transition text-left ${accent}`}
    >
      {label}
    </button>
  );
}

interface ActionGroup {
  title: string;
  icon: string;
  actions: { label: string; prompt: string; tooltip: string; accent: string; clone?: boolean }[];
}

const POSTGRES_ACTIONS: ActionGroup[] = [
  {
    title: "PostgreSQL Operations",
    icon: "🐘",
    actions: [
      { label: "🏥 Health Check", prompt: "Run a full health check: connections, slow queries, vacuum status, table bloat, index health, and TXID wraparound.", tooltip: "Comprehensive PostgreSQL health audit", accent: "hover:border-emerald-500 hover:bg-emerald-950/40 hover:text-emerald-300" },
      { label: "🐢 Slow Queries", prompt: "Use get_slow_queries to show the top 10 slowest queries from pg_stat_statements with their mean execution time.", tooltip: "Top slow queries from pg_stat_statements", accent: "hover:border-amber-500 hover:bg-amber-950/40 hover:text-amber-300" },
      { label: "👥 Active Sessions", prompt: "Use get_active_sessions to show all currently active backends.", tooltip: "Active sessions from pg_stat_activity", accent: "hover:border-cyan-500 hover:bg-cyan-950/40 hover:text-cyan-300" },
      { label: "⏳ Wait Events", prompt: "Use get_wait_events to show what backends are waiting on, grouped by wait_event_type.", tooltip: "Wait events from pg_stat_activity", accent: "hover:border-fuchsia-500 hover:bg-fuchsia-950/40 hover:text-fuchsia-300" },
      { label: "🧹 Vacuum & Bloat", prompt: "Use get_vacuum_status and get_table_bloat to report dead tuples, last vacuum/autovacuum times, and table bloat ratios.", tooltip: "Vacuum status, dead tuples, table bloat — PostgreSQL MVCC maintenance", accent: "hover:border-lime-500 hover:bg-lime-950/40 hover:text-lime-300" },
      { label: "📈 Index Analysis", prompt: "Use get_index_usage to report unused indexes and index bloat.", tooltip: "Index usage stats — find unused indexes", accent: "hover:border-violet-500 hover:bg-violet-950/40 hover:text-violet-300" },
      { label: "🔒 Blocking Chains", prompt: "Use detect_blocking_chains to show who is blocking whom and for how long.", tooltip: "Detect blocking chains and head blockers", accent: "hover:border-red-500 hover:bg-red-950/40 hover:text-red-300" },
      { label: "🛡️ TXID Wraparound", prompt: "Use check_txid_wraparound to check transaction ID wraparound proximity — a critical PostgreSQL safety check.", tooltip: "PG-specific: transaction ID wraparound risk", accent: "hover:border-orange-500 hover:bg-orange-950/40 hover:text-orange-300" },
      { label: "🎭 Data Masking", prompt: "Use get_masking_policies to list current masking views, then suggest setup_data_masking on sensitive columns.", tooltip: "Dynamic data masking on sensitive columns", accent: "hover:border-purple-500 hover:bg-purple-950/40 hover:text-purple-300" },
      { label: "👤 Manage Users", prompt: "Help me manage PostgreSQL users — list current users and their roles, and offer to create_db_user or drop_db_user.", tooltip: "Create/drop users, manage roles & grants", accent: "hover:border-pink-500 hover:bg-pink-950/40 hover:text-pink-300" },
      { label: "⚡ Run SQL", prompt: "I need to run a custom SQL statement (DDL or DML). Ask me what to run.", tooltip: "Execute DDL/DML — CREATE TABLE, ALTER TABLE, INSERT, UPDATE, DELETE", accent: "hover:border-rose-500 hover:bg-rose-950/40 hover:text-rose-300" },
    ],
  },
];

const MYSQL_ACTIONS: ActionGroup[] = [
  {
    title: "MySQL Operations",
    icon: "🐬",
    actions: [
      { label: "🏥 Health Check", prompt: "Run a full MySQL health check: connections, processlist, InnoDB buffer pool, slow queries, and index usage.", tooltip: "Comprehensive MySQL health audit", accent: "hover:border-emerald-500 hover:bg-emerald-950/40 hover:text-emerald-300" },
      { label: "🐢 Slow Queries", prompt: "Use get_slow_queries to show the top 10 slowest queries from performance_schema.events_statements_summary_by_digest.", tooltip: "Top slow queries from performance_schema", accent: "hover:border-amber-500 hover:bg-amber-950/40 hover:text-amber-300" },
      { label: "📋 Processlist", prompt: "Use get_processlist to show all active connections (SHOW PROCESSLIST equivalent).", tooltip: "MySQL-specific: SHOW PROCESSLIST view", accent: "hover:border-cyan-500 hover:bg-cyan-950/40 hover:text-cyan-300" },
      { label: "🔧 InnoDB Status", prompt: "Use get_innodb_status to show buffer pool size, hit ratio, dirty pages, and row lock metrics.", tooltip: "MySQL-specific: InnoDB engine internals", accent: "hover:border-blue-500 hover:bg-blue-950/40 hover:text-blue-300" },
      { label: "📈 Index Usage", prompt: "Use get_index_usage to report index usage from sys.schema_unused_indexes.", tooltip: "Find unused indexes via sys schema", accent: "hover:border-violet-500 hover:bg-violet-950/40 hover:text-violet-300" },
      { label: "🔒 Blocking Chains", prompt: "Use detect_blocking_chains to show InnoDB row lock waits — who is blocking whom.", tooltip: "InnoDB lock waits and blocking chains", accent: "hover:border-red-500 hover:bg-red-950/40 hover:text-red-300" },
      { label: "🎯 Index Recommend", prompt: "Pick the largest table from list_tables and call recommend_index on it.", tooltip: "Suggest indexes for a table based on stats", accent: "hover:border-fuchsia-500 hover:bg-fuchsia-950/40 hover:text-fuchsia-300" },
      { label: "🎭 Data Masking", prompt: "Use setup_data_masking to create masking views over sensitive columns.", tooltip: "Data masking via MySQL views", accent: "hover:border-purple-500 hover:bg-purple-950/40 hover:text-purple-300" },
      { label: "👤 Manage Users", prompt: "Help me manage MySQL users — list current users and offer to create_db_user or drop_db_user.", tooltip: "Create/drop users and manage privileges", accent: "hover:border-pink-500 hover:bg-pink-950/40 hover:text-pink-300" },
      { label: "⚡ Run SQL", prompt: "I need to run a custom SQL statement. Ask me what to run.", tooltip: "Execute DDL/DML against the live MySQL", accent: "hover:border-rose-500 hover:bg-rose-950/40 hover:text-rose-300" },
    ],
  },
];

const ORACLE_ACTIONS: ActionGroup[] = [
  {
    title: "Oracle Operations",
    icon: "🦅",
    actions: [
      { label: "🏥 Health Check", prompt: "Run an Oracle health check: tablespaces, sessions, wait events, redo log status, and top SQL.", tooltip: "Comprehensive Oracle EE health audit", accent: "hover:border-emerald-500 hover:bg-emerald-950/40 hover:text-emerald-300" },
      { label: "💽 Tablespaces", prompt: "Use list_tablespaces to show all tablespaces with usage, free space, and autoextend status.", tooltip: "Oracle-specific: tablespace usage and autoextend", accent: "hover:border-blue-500 hover:bg-blue-950/40 hover:text-blue-300" },
      { label: "↩️ UNDO / Redo Logs", prompt: "Use get_redo_log_status to check redo log groups and switch frequency. Then identify any UNDO tablespace pressure or stuck transactions.", tooltip: "Oracle-specific: redo log groups, switch rate, UNDO tablespace pressure", accent: "hover:border-orange-500 hover:bg-orange-950/40 hover:text-orange-300" },
      { label: "📊 ASH Top SQL", prompt: "Use get_ash_top_sql for the last 30 minutes to identify the most resource-intensive SQL.", tooltip: "Active Session History — top SQL by activity (Oracle-specific)", accent: "hover:border-fuchsia-500 hover:bg-fuchsia-950/40 hover:text-fuchsia-300" },
      { label: "⏳ Wait Events", prompt: "Use get_wait_events to show current wait events grouped by wait class.", tooltip: "Current wait events by class (Oracle wait interface)", accent: "hover:border-cyan-500 hover:bg-cyan-950/40 hover:text-cyan-300" },
      { label: "🐢 Slow SQL", prompt: "Use get_slow_queries to show the top 10 slowest SQL statements from v$sqlarea.", tooltip: "Top slow SQL from v$sqlarea", accent: "hover:border-amber-500 hover:bg-amber-950/40 hover:text-amber-300" },
      { label: "👥 Active Sessions", prompt: "Use get_active_sessions to list active sessions from v$session.", tooltip: "Active sessions from v$session", accent: "hover:border-sky-500 hover:bg-sky-950/40 hover:text-sky-300" },
      { label: "🔒 Blocking Sessions", prompt: "Use get_blocking_sessions to identify blocking chains and head blockers.", tooltip: "Blocking sessions from v$lock / v$session", accent: "hover:border-red-500 hover:bg-red-950/40 hover:text-red-300" },
      { label: "📈 Index Usage", prompt: "Use get_index_usage on the largest schema to find unused indexes.", tooltip: "Index usage stats — unused indexes", accent: "hover:border-violet-500 hover:bg-violet-950/40 hover:text-violet-300" },
      { label: "🧮 Gather Stats", prompt: "Help me gather optimizer stats: ask me which schema and table, then call gather_table_stats.", tooltip: "Oracle-specific: DBMS_STATS.GATHER_TABLE_STATS", accent: "hover:border-lime-500 hover:bg-lime-950/40 hover:text-lime-300" },
      { label: "⚙️ Modify Parameter", prompt: "Help me modify an Oracle init parameter: ask me which parameter, value, and scope (memory, spfile, both).", tooltip: "Oracle-specific: ALTER SYSTEM SET parameter", accent: "hover:border-yellow-500 hover:bg-yellow-950/40 hover:text-yellow-300" },
      { label: "⚡ Run SQL", prompt: "I need to run a custom SQL or PL/SQL block. Ask me what to run.", tooltip: "Execute SQL / PL/SQL against live Oracle", accent: "hover:border-rose-500 hover:bg-rose-950/40 hover:text-rose-300" },
    ],
  },
];

const DYNAMODB_ACTIONS: ActionGroup[] = [
  {
    title: "DynamoDB Operations",
    icon: "⚡",
    actions: [
      { label: "📋 List Tables", prompt: "List all DynamoDB tables in the account.", tooltip: "List every DynamoDB table in the region", accent: "hover:border-emerald-500 hover:bg-emerald-950/40 hover:text-emerald-300" },
      { label: "🔍 Describe Table", prompt: "Describe the selected table — show keys, GSIs, capacity, and item count.", tooltip: "Table schema: keys, GSIs/LSIs, capacity, item count", accent: "hover:border-blue-500 hover:bg-blue-950/40 hover:text-blue-300" },
      { label: "🔴 Throttling", prompt: "Check whether the table is throttling — look at consumed vs provisioned capacity and any ThrottledRequests metric.", tooltip: "Throttled read/write events from CloudWatch", accent: "hover:border-red-500 hover:bg-red-950/40 hover:text-red-300" },
      { label: "🔥 Hot Partitions", prompt: "Check for hot partition keys via Contributor Insights.", tooltip: "DynamoDB-specific: hot partition keys (Contributor Insights)", accent: "hover:border-orange-500 hover:bg-orange-950/40 hover:text-orange-300" },
      { label: "📈 GSI Backpressure", prompt: "Check the GSI backfill status and any backpressure.", tooltip: "DynamoDB-specific: GSI backfilling and write throttles", accent: "hover:border-violet-500 hover:bg-violet-950/40 hover:text-violet-300" },
      { label: "📊 Table Metrics", prompt: "Show CloudWatch metrics for the selected table: RCU/WCU consumed, latency, throttles.", tooltip: "Consumed capacity, latency, throttle metrics", accent: "hover:border-sky-500 hover:bg-sky-950/40 hover:text-sky-300" },
      { label: "⬆️ Scale Capacity", prompt: "Recommend RCU/WCU adjustments for the selected table based on consumption.", tooltip: "Modify provisioned capacity (RCU/WCU)", accent: "hover:border-yellow-500 hover:bg-yellow-950/40 hover:text-yellow-300" },
      { label: "🔄 Billing Mode", prompt: "What billing mode is the table on? Recommend whether to switch between on-demand and provisioned.", tooltip: "On-demand ↔ provisioned", accent: "hover:border-purple-500 hover:bg-purple-950/40 hover:text-purple-300" },
      { label: "➕ Add GSI", prompt: "Help me add a Global Secondary Index — ask for partition key, sort key, and projection.", tooltip: "Add a GSI for new access patterns", accent: "hover:border-green-500 hover:bg-green-950/40 hover:text-green-300" },
      { label: "🔎 Query Items", prompt: "Help me query items from the selected table — ask for partition key value (and sort key if applicable).", tooltip: "Query by partition key", accent: "hover:border-cyan-500 hover:bg-cyan-950/40 hover:text-cyan-300" },
      { label: "💾 Backup Now", prompt: "Create an on-demand backup of the selected table.", tooltip: "On-demand backup", accent: "hover:border-teal-500 hover:bg-teal-950/40 hover:text-teal-300" },
      { label: "📤 Export to S3", prompt: "Export the selected table to S3 (point-in-time export, no RCU consumed).", tooltip: "PITR export to S3 — no capacity used", accent: "hover:border-indigo-500 hover:bg-indigo-950/40 hover:text-indigo-300" },
    ],
  },
];

// Shared RDS / Aurora actions (PG and MySQL — both Aurora-capable).
const AURORA_RDS_ACTIONS: ActionGroup = {
  title: "RDS / Aurora Ops",
  icon: "☁️",
  actions: [
    { label: "📊 System Metrics", prompt: "Use get_cloudwatch_metrics to show CPU, memory, IOPS, disk, and connection metrics for the selected instance.", tooltip: "CloudWatch metrics: CPU/memory/IOPS/disk/connections", accent: "hover:border-sky-500 hover:bg-sky-950/40 hover:text-sky-300" },
    { label: "🔍 Cluster Info", prompt: "Use get_replication_status for the selected cluster — show writer, readers, and replication lag.", tooltip: "Cluster topology: writer, readers, endpoints", accent: "hover:border-indigo-500 hover:bg-indigo-950/40 hover:text-indigo-300" },
    { label: "📋 Add Replica", prompt: "Help me create a read replica for the selected cluster — ask for replica identifier and instance class.", tooltip: "Add a read replica via create_read_replica", accent: "hover:border-green-500 hover:bg-green-950/40 hover:text-green-300" },
    { label: "📈 Auto Scaling", prompt: "Use get_autoscaling_status, then offer to configure_aurora_autoscaling for read replicas based on CPU.", tooltip: "Aurora Auto Scaling for read replicas", accent: "hover:border-yellow-500 hover:bg-yellow-950/40 hover:text-yellow-300" },
    { label: "⬆️ Resize DB", prompt: "Use get_instance_details, then suggest a new instance class via modify_instance_class.", tooltip: "Vertical scale: change instance class", accent: "hover:border-orange-500 hover:bg-orange-950/40 hover:text-orange-300" },
    { label: "💾 Backup Now", prompt: "Trigger an on-demand snapshot of the selected cluster via trigger_backup.", tooltip: "On-demand snapshot/backup", accent: "hover:border-teal-500 hover:bg-teal-950/40 hover:text-teal-300" },
    { label: "🔄 Replicate Tables", prompt: "Replicate selected tables from production to dev with optional column-level masking.", tooltip: "Replicate tables to a lower environment with masking", accent: "hover:border-blue-500 hover:bg-blue-950/40 hover:text-blue-300", clone: true },
  ],
};

// Oracle is RDS but not Aurora — smaller, more conservative action set.
const ORACLE_RDS_ACTIONS: ActionGroup = {
  title: "RDS Ops",
  icon: "☁️",
  actions: [
    { label: "📊 System Metrics", prompt: "Use get_cloudwatch_metrics for the Oracle RDS instance — show CPU, memory, IOPS, disk, and connections.", tooltip: "CloudWatch metrics for the Oracle instance", accent: "hover:border-sky-500 hover:bg-sky-950/40 hover:text-sky-300" },
    { label: "🔍 Instance Details", prompt: "Use get_rds_instance_details and get_instance_details to summarize Oracle version, instance class, storage, and uptime.", tooltip: "RDS-level instance class, storage, Multi-AZ + Oracle internals", accent: "hover:border-indigo-500 hover:bg-indigo-950/40 hover:text-indigo-300" },
    { label: "⬆️ Resize DB", prompt: "Use modify_instance_class to scale the Oracle RDS instance vertically. Ask me for the new class.", tooltip: "Vertical scale: change instance class", accent: "hover:border-orange-500 hover:bg-orange-950/40 hover:text-orange-300" },
    { label: "💾 Backup Now", prompt: "Trigger an on-demand snapshot of the Oracle RDS instance via trigger_backup.", tooltip: "On-demand snapshot/backup", accent: "hover:border-teal-500 hover:bg-teal-950/40 hover:text-teal-300" },
  ],
};

export default function FleetPanel({ selectedDb, onSelectDb, agentType, onCloneClick, onQuickAction }: FleetPanelProps) {
  const dbs = databases[agentType] || [];

  let engineGroups: ActionGroup[] = [];
  let rdsGroup: ActionGroup | null = null;

  if (agentType === "postgresql") { engineGroups = POSTGRES_ACTIONS; rdsGroup = AURORA_RDS_ACTIONS; }
  else if (agentType === "mysql") { engineGroups = MYSQL_ACTIONS; rdsGroup = AURORA_RDS_ACTIONS; }
  else if (agentType === "oracle") { engineGroups = ORACLE_ACTIONS; rdsGroup = ORACLE_RDS_ACTIONS; }
  else if (agentType === "dynamodb") { engineGroups = DYNAMODB_ACTIONS; rdsGroup = null; }

  const handleAction = (prompt: string) => onQuickAction?.(prompt);

  return (
    <div className="w-72 flex-shrink-0 overflow-y-auto border-r border-slate-700 bg-slate-900/50 p-4 scrollbar-thin">
      <h2 className="mb-3 text-sm font-semibold text-slate-400 uppercase tracking-wider">
        Database Fleet
      </h2>

      {/* Database List */}
      <div className="space-y-2">
        {dbs.map((db) => (
          <button
            key={db.id}
            onClick={() => onSelectDb(db.id)}
            className={`w-full rounded-lg border p-3 text-left transition-all ${
              selectedDb === db.id
                ? "border-blue-500 bg-blue-950/50"
                : "border-slate-700 bg-slate-800/50 hover:border-slate-600 hover:bg-slate-800"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium truncate">{db.name}</span>
              <EnvBadge env={db.env} />
            </div>
            <div className="mt-1.5 flex items-center justify-between">
              <HealthBadge score={db.health} />
              <span className="text-[10px] text-slate-500">{db.lastCheck}</span>
            </div>
          </button>
        ))}
      </div>

      {/* Replication Target Selector */}
      {agentType !== "dynamodb" && (
        <div className="mt-6">
          <h3 className="mb-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Replication Target
          </h3>
          <select className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300 focus:border-blue-500 focus:outline-none">
            <option value="">Select target...</option>
            {dbs.filter(d => d.env === "development").map(db => (
              <option key={db.id} value={db.id}>{db.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Engine-specific actions */}
      {engineGroups.map(group => (
        <div className="mt-5" key={group.title}>
          <h3 className="mb-2 flex items-center gap-1 text-xs font-semibold text-slate-400 uppercase tracking-wider">
            <span>{group.icon}</span>
            <span>{group.title}</span>
          </h3>
          <div className="grid grid-cols-2 gap-1.5">
            {group.actions.map(a => (
              <ActionButton key={a.label} label={a.label} prompt={a.prompt} tooltip={a.tooltip} accent={a.accent} onClick={handleAction} />
            ))}
          </div>
        </div>
      ))}

      {/* RDS / Aurora actions (separate, shared management ops) */}
      {rdsGroup && (
        <div className="mt-5">
          <h3 className="mb-2 flex items-center gap-1 text-xs font-semibold text-slate-400 uppercase tracking-wider">
            <span>{rdsGroup.icon}</span>
            <span>{rdsGroup.title}</span>
          </h3>
          <div className="grid grid-cols-2 gap-1.5">
            {rdsGroup.actions.map(a => (
              ('clone' in a && a.clone)
                ? <button key={a.label} onClick={onCloneClick} data-tooltip={a.tooltip} className={`rounded-lg bg-slate-800 border border-slate-700 px-2 py-2 text-[11px] font-medium text-slate-300 transition text-left ${a.accent}`}>{a.label}</button>
                : <ActionButton key={a.label} label={a.label} prompt={a.prompt} tooltip={a.tooltip} accent={a.accent} onClick={handleAction} />
            ))}
          </div>
        </div>
      )}

      {/* User-defined Custom Buttons (R2.4) */}
      <CustomButtonsGroup
        engine={agentType as Engine}
        onPromptInvoke={(prompt) => onQuickAction?.(prompt)}
      />
    </div>
  );
}
