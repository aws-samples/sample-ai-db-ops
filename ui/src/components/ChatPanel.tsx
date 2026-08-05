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

import { useState, useRef, useEffect } from "react";
import FileUpload from "@/components/FileUpload";
import Markdown from "@/components/Markdown";
import { withUserHeader } from "@/lib/auth/client";
import { redactSecretAssignments } from "@/lib/redact";
import { newSessionId } from "@/lib/session";

interface ChatPanelProps {
  selectedDb: string | null;
  agentType: string;
  onTraceUpdate?: (step: any) => void;
  externalPrompt?: string | null;
  onExternalPromptConsumed?: () => void;
}

/** A Tier-3 operation the agent proposed and paused on, awaiting approval. */
interface PendingApproval {
  interrupt_id?: string;
  tool: string;
  input?: Record<string, unknown>;
  /** Binds an approval to this exact tool + argument set. */
  fingerprint: string;
  message?: string;
}

/** One operator decision, sent back to the agent on the follow-up invocation. */
interface ApprovalDecision {
  tool: string;
  fingerprint: string;
  decision: "APPLY" | "DENY";
}

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  xpEarned?: number;
  toolsUsed?: string[];
  /** Present when the agent stopped to ask for Tier-3 approval. */
  pendingApprovals?: PendingApproval[];
  /** The prompt that produced this turn, replayed when approving. */
  sourcePrompt?: string;
}

const QUICK_ACTIONS = [
  { label: "🔍 Health Check", prompt: "Run a full health check" },
  { label: "🐢 Slow Queries", prompt: "Show me the top 10 slow queries" },
  { label: "📊 Connections", prompt: "Show connection summary" },
  { label: "🧹 Vacuum Status", prompt: "Check vacuum status and bloat" },
  { label: "📈 Index Analysis", prompt: "Check for missing and unused indexes" },
  { label: "🔄 Clone to Dev", prompt: "Clone this database to the dev environment with data masking" },
  { label: "🎭 Setup Masking", prompt: "Setup data masking on sensitive columns" },
  { label: "📋 Replication", prompt: "Show replication status and create a read replica" },
];

export default function ChatPanel({ selectedDb, agentType, onTraceUpdate, externalPrompt, onExternalPromptConsumed }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");

  // Add welcome message on client only to avoid hydration mismatch
  useEffect(() => {
    if (messages.length === 0) {
      setMessages([{
        id: "welcome",
        role: "assistant",
        content: "👋 Welcome to DB Ops! Select a database from the fleet panel and ask me anything — health checks, slow queries, index recommendations, data masking, replication, or cloning to lower environments.\n\nI'm connected to your **live databases** in VPC. All results are real.",
        timestamp: new Date(),
      }]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [isLoading, setIsLoading] = useState(false);
  // Fingerprints the operator has already decided on, so an approval card
  // cannot be actioned twice.
  const [resolvedApprovals, setResolvedApprovals] = useState<Set<string>>(new Set());
  const [uploadedFile, setUploadedFile] = useState<{ fileName: string; tableName: string; headers: string[]; rows: string[][]; rowCount: number } | null>(null);
  // Lazily initialised so the CSPRNG is only touched on the client.
  const [sessionId, setSessionId] = useState(newSessionId);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async (
    text: string,
    opts?: { approvals?: ApprovalDecision[]; suppressUserMessage?: boolean },
  ) => {
    if (!text.trim()) return;

    // When replaying a prompt to carry an approval decision, don't echo the
    // original request back into the transcript a second time.
    if (!opts?.suppressUserMessage) {
      const userMsg: Message = {
        id: Date.now().toString(),
        role: "user",
        content: text,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);
    }
    setInput("");
    setIsLoading(true);

    // Simulate API call (replace with real AgentCore invoke)
    try {
      // Trace: user input. `detail` carries metadata only — the full text lives
      // in `raw`, which the Logs tab renders (TracePanel reads `raw || detail`,
      // so duplicating the prompt into both served no purpose). `raw` is passed
      // through secret redaction because an operator may paste a connection
      // string or password into the chat and the panel supports copying its
      // contents to the clipboard.
      onTraceUpdate?.({
        type: "user_input",
        label: text.slice(0, 40),
        status: "success",
        detail: `${text.length} chars`,
        raw: redactSecretAssignments(text),
      });

      // Trace: agent call
      const agentLabel =
        agentType === "postgresql" ? "dbops_postgresql"
        : agentType === "mysql" ? "dbops_mysql"
        : agentType === "oracle" ? "dbops_oracle"
        : "dbops_dynamodb";
      const dbLabel = selectedDb || (
        agentType === "postgresql" ? "Aurora PostgreSQL"
        : agentType === "mysql" ? "Aurora MySQL"
        : agentType === "oracle" ? "Oracle EE 19c"
        : "DynamoDB"
      );
      onTraceUpdate?.({ type: "agent_thinking", label: `Calling ${agentLabel}`, status: "running", detail: `DB: ${dbLabel}` });
      onTraceUpdate?.({ type: "tool_call", label: `Connecting to ${dbLabel}`, status: "running" });

      const startTime = Date.now();
      const response = await fetch("/api/invoke", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: selectedDb ? `[Database: ${selectedDb}] ${text}` : text,
          user_id: process.env.NEXT_PUBLIC_USER_ID || "dbops-user",
          agent_type: agentType,
          session_id: sessionId,
          history: messages.filter(m => m.role !== "system").slice(-6).map(m => ({
            role: m.role,
            content: m.content.slice(0, 500),
          })),
          // Operator decisions for specific pending operations. Empty on a
          // normal turn; populated only by an explicit APPLY/DENY click.
          approvals: opts?.approvals ?? [],
        }),
      });

      const data = await response.json();

      // The agent paused before running a Tier-3 tool. Surface the exact
      // operation for the operator to approve or deny; nothing has executed.
      if (data.awaiting_approval && Array.isArray(data.pending_approvals) && data.pending_approvals.length > 0) {
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now() + 1}-approval`,
            role: "assistant",
            content:
              "This request requires a **Tier-3 (mutating) operation**. Review the exact operation below and approve it to proceed.",
            timestamp: new Date(),
            pendingApprovals: data.pending_approvals as PendingApproval[],
            sourcePrompt: text,
          },
        ]);
        onTraceUpdate?.({
          type: "tool_call",
          label: "Tier-3 approval required",
          status: "running",
          detail: (data.pending_approvals as PendingApproval[])
            .map((r) => r.tool)
            .join(", "),
        });
        setIsLoading(false);
        return;
      }

      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: (data.response || data.error || "No response received.").replace(/<\/?previous_results>/g, "").replace(/<\/?result>/g, "").replace(/<\/?tool_call_result>/g, "").replace(/<tool call result>[\s\S]*?<\/tool call result>/g, "").replace(/<tool_call_result>[\s\S]*?<\/tool_call_result>/g, "").trim(),
        timestamp: new Date(),
        xpEarned: data.xp_earned,
        toolsUsed: data.tools_used,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Trace: response received
      const elapsed = Date.now() - startTime;
      
      // Extract tool calls from response text
      const responseText = data.response || "";
      const toolPatterns = [
        { pattern: /list_databases|List.*databases/i, tool: "list_databases", db: "pg_database" },
        { pattern: /get_slow_queries|slow.*quer/i, tool: "get_slow_queries", db: "pg_stat_statements" },
        { pattern: /get_active_sessions|active.*session/i, tool: "get_active_sessions", db: "pg_stat_activity" },
        { pattern: /get_wait_events|wait.*event/i, tool: "get_wait_events", db: "pg_stat_activity" },
        { pattern: /get_vacuum_status|vacuum/i, tool: "get_vacuum_status", db: "pg_stat_user_tables" },
        { pattern: /get_index_usage|index.*usage|unused.*index/i, tool: "get_index_usage", db: "pg_stat_user_indexes" },
        { pattern: /get_table_bloat|bloat/i, tool: "get_table_bloat", db: "pg_stat_user_tables" },
        { pattern: /recommend_index/i, tool: "recommend_index", db: "pg_stats" },
        { pattern: /create_index|CREATE INDEX/i, tool: "create_index", db: "DDL execution" },
        { pattern: /execute_sql|CREATE TABLE|ALTER TABLE|INSERT/i, tool: "execute_sql", db: "SQL execution" },
        { pattern: /detect_blocking/i, tool: "detect_blocking_chains", db: "pg_locks" },
        { pattern: /get_cloudwatch|CPU|IOPS|memory/i, tool: "get_cloudwatch_metrics", db: "CloudWatch" },
        { pattern: /describe.*table|DescribeTable/i, tool: "describe_table", db: "DynamoDB API" },
        { pattern: /get_table_metrics|consumed.*capacity/i, tool: "get_table_metrics", db: "CloudWatch" },
        { pattern: /InnoDB|innodb_status/i, tool: "get_innodb_status", db: "performance_schema" },
        { pattern: /processlist|PROCESSLIST/i, tool: "get_processlist", db: "information_schema" },
        { pattern: /connections.*summary|max_connections/i, tool: "get_connections_summary", db: "pg_stat_activity" },
      ];

      const detectedTools = toolPatterns.filter(p => p.pattern.test(responseText));
      for (const t of detectedTools.slice(0, 4)) {
        onTraceUpdate?.({ type: "tool_call", label: t.tool, status: "success", detail: `Source: ${t.db}` });
      }

      // `detail` is already metadata only. `raw` carries the response for the
      // Logs tab, redacted for the same reason as the prompt above: an agent
      // reply can quote back a connection string or a credential it was shown.
      onTraceUpdate?.({
        type: "agent_response",
        label: "Response delivered",
        status: "success",
        duration: elapsed,
        detail: `${detectedTools.length} tool(s) used`,
        raw: redactSecretAssignments(responseText),
      });
    } catch {
      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: "⚠️ Failed to reach the agent. Make sure the backend API is running.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    }

    setIsLoading(false);
  };

  /**
   * Record an operator decision for one pending Tier-3 operation and replay the
   * original prompt carrying it. The decision is bound to the operation's
   * fingerprint, so it authorizes only this exact tool and argument set.
   */
  const respondToApproval = (
    msg: Message,
    req: PendingApproval,
    decision: "APPLY" | "DENY",
  ) => {
    setResolvedApprovals((prev) => new Set(prev).add(req.fingerprint));
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-decision`,
        role: "system",
        content:
          decision === "APPLY"
            ? `Approved \`${req.tool}\` — sending for execution.`
            : `Denied \`${req.tool}\` — the operation was not executed.`,
        timestamp: new Date(),
      },
    ]);
    void sendMessage(msg.sourcePrompt ?? "", {
      approvals: [
        { tool: req.tool, fingerprint: req.fingerprint, decision },
      ],
      suppressUserMessage: true,
    });
  };

  // Handle external prompts from quick actions — new session each time
  useEffect(() => {
    if (externalPrompt) {
      setSessionId(newSessionId());
      setMessages([]);
      sendMessage(externalPrompt);
      onExternalPromptConsumed?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalPrompt]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Context Bar */}
      <div className="flex items-center gap-3 border-b border-slate-700 bg-slate-900/80 px-4 py-2">
        <span className="text-xs text-slate-500">Agent:</span>
        <span className="rounded bg-slate-700 px-2 py-0.5 text-xs font-medium">
          {agentType === "postgresql" ? "🐘 PostgreSQL"
            : agentType === "mysql" ? "🐬 MySQL"
            : agentType === "oracle" ? "🦅 Oracle"
            : "⚡ DynamoDB"}
        </span>
        {selectedDb && (
          <>
            <span className="text-xs text-slate-500">→</span>
            <span className="rounded bg-blue-900/50 border border-blue-700 px-2 py-0.5 text-xs font-medium text-blue-300">
              {selectedDb}
            </span>
          </>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 border border-slate-700 text-slate-200"
              }`}
            >
              {msg.role === "user" ? (
                <div className="whitespace-pre-wrap text-sm leading-relaxed">
                  {msg.content}
                </div>
              ) : (
                <Markdown content={msg.content} />
              )}
              {msg.pendingApprovals && msg.pendingApprovals.length > 0 && (
                <div className="mt-3 space-y-3">
                  {msg.pendingApprovals.map((req) => {
                    const resolved = resolvedApprovals.has(req.fingerprint);
                    return (
                      <div
                        key={req.fingerprint}
                        className="rounded-xl border border-amber-600 bg-amber-950/30 p-3"
                      >
                        <div className="flex items-center gap-2 text-sm font-semibold text-amber-300">
                          <span aria-hidden="true">⚠️</span>
                          <span>Tier-3 approval required</span>
                        </div>
                        <p className="mt-2 text-xs text-slate-300">
                          This operation modifies the database and has{" "}
                          <span className="font-semibold text-slate-100">not</span>{" "}
                          been executed. It runs only if you approve it.
                        </p>
                        <div className="mt-2 rounded-lg bg-slate-950/60 p-2 font-mono text-[11px] text-slate-200">
                          <div>
                            <span className="text-slate-500">tool: </span>
                            {req.tool}
                          </div>
                          {Object.entries(req.input ?? {}).map(([key, value]) => (
                            <div key={key} className="break-all">
                              <span className="text-slate-500">{key}: </span>
                              {typeof value === "string" ? value : JSON.stringify(value)}
                            </div>
                          ))}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => respondToApproval(msg, req, "APPLY")}
                            disabled={isLoading || resolved}
                            className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            APPLY — run this operation
                          </button>
                          <button
                            type="button"
                            onClick={() => respondToApproval(msg, req, "DENY")}
                            disabled={isLoading || resolved}
                            className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            DENY
                          </button>
                        </div>
                        <div className="mt-2 break-all text-[10px] text-slate-500">
                          fingerprint: {req.fingerprint.slice(0, 24)}…
                          {resolved && " (decision recorded)"}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {msg.xpEarned && (
                <div className="mt-2 text-xs text-green-400">
                  ✨ +{msg.xpEarned} XP earned
                </div>
              )}
              <div className="mt-1 text-[10px] text-slate-500">
                {msg.timestamp.toLocaleTimeString()}
              </div>
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-slate-800 border border-slate-700 px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <span className="animate-pulse">●</span>
                <span className="animate-pulse delay-100">●</span>
                <span className="animate-pulse delay-200">●</span>
                <span className="ml-2">Querying live database...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-slate-700 bg-slate-900 p-4">
        {/* Attached file indicator */}
        {uploadedFile && (
          <div className="mb-2 flex items-center gap-2 rounded-lg bg-blue-950/40 border border-blue-700 px-3 py-1.5">
            <span className="text-xs text-blue-300">📎 {uploadedFile.fileName}</span>
            <button onClick={() => setUploadedFile(null)} className="text-xs text-slate-500 hover:text-red-400">✕</button>
          </div>
        )}

        <div className="flex items-center gap-2">
          {/* File attach button */}
          <label className="cursor-pointer rounded-xl border border-slate-600 bg-slate-800 p-3 hover:border-blue-500 hover:bg-slate-700 transition" data-tooltip="Attach CSV, XLS, or JSON file">
            <input
              type="file"
              accept=".csv,.xlsx,.xls,.json"
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const formData = new FormData();
                formData.append("file", file);
                try {
                  const res = await fetch("/api/upload", {
                    method: "POST",
                    headers: withUserHeader(),
                    body: formData,
                  });
                  const data = await res.json();
                  if (data.s3_uri) {
                    setUploadedFile({ fileName: file.name, tableName: "", headers: [], rows: [], rowCount: 0 });
                    // Store S3 URI for when user sends the message
                    (window as any).__dbops_s3uri = data.s3_uri;
                    (window as any).__dbops_filename = file.name;
                    (window as any).__dbops_filesize = data.file_size;
                  }
                } catch { /* ignore */ }
                e.target.value = "";
              }}
            />
            <span className="text-lg">📎</span>
          </label>

          {/* Text input */}
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                let msg = input;
                const s3Uri = (window as any).__dbops_s3uri;
                if (s3Uri && uploadedFile) {
                  const fn = (window as any).__dbops_filename;
                  const sz = (window as any).__dbops_filesize;
                  msg = `${input}\n\n[Attached file: "${fn}" (${Math.round(sz / 1024)}KB) uploaded to ${s3Uri}]`;
                  (window as any).__dbops_s3uri = null;
                  setUploadedFile(null);
                }
                sendMessage(msg);
              }
            }}
            placeholder={uploadedFile ? `Describe what to do with ${uploadedFile.fileName}...` : selectedDb ? `Ask about ${selectedDb}...` : "Select a database and ask anything..."}
            className="flex-1 rounded-xl border border-slate-600 bg-slate-800 px-4 py-3 text-sm text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />

          {/* Send button */}
          <button
            onClick={() => {
              let msg = input;
              const s3Uri = (window as any).__dbops_s3uri;
              if (s3Uri && uploadedFile) {
                const fn = (window as any).__dbops_filename;
                const sz = (window as any).__dbops_filesize;
                msg = `${input}\n\n[Attached file: "${fn}" (${Math.round(sz / 1024)}KB) uploaded to ${s3Uri}]`;
                (window as any).__dbops_s3uri = null;
                setUploadedFile(null);
              }
              sendMessage(msg);
            }}
            disabled={isLoading || (!input.trim() && !uploadedFile)}
            className="rounded-xl bg-blue-600 px-5 py-3 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
