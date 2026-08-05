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

import { useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Node,
  Edge,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

export interface TraceStep {
  id: string;
  type: "user_input" | "agent_thinking" | "tool_call" | "agent_response" | "session_start";
  label: string;
  status: "running" | "success" | "failed";
  duration?: number;
  detail?: string;
  timestamp: Date;
  /**
   * Optional raw text payload — used by the Logs tab to show prompts and the
   * full response body, and by the Queries tab to extract SQL/DynamoDB calls.
   */
  raw?: string;
}

interface TracePanelProps {
  steps: TraceStep[];
  isVisible: boolean;
  onToggle: () => void;
  sessionId: string;
}

const nodeColors: Record<string, { bg: string; border: string; text: string }> = {
  session_start: { bg: "#1e293b", border: "#475569", text: "#94a3b8" },
  user_input: { bg: "#1e3a5f", border: "#3b82f6", text: "#93c5fd" },
  agent_thinking: { bg: "#422006", border: "#f59e0b", text: "#fcd34d" },
  tool_call: { bg: "#2e1065", border: "#8b5cf6", text: "#c4b5fd" },
  agent_response: { bg: "#052e16", border: "#22c55e", text: "#86efac" },
};

const nodeIcons: Record<string, string> = {
  session_start: "🚀",
  user_input: "💬",
  agent_thinking: "🧠",
  tool_call: "⚙️",
  agent_response: "✅",
};

type Tab = "flow" | "logs" | "queries";

interface ExtractedQuery {
  language: "SQL" | "PL/SQL" | "DynamoDB";
  text: string;
  source: string;        // step label
  timestamp: Date;
}

const SQL_KEYWORD_RE = /\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+(?:TABLE|INDEX|VIEW|USER|DATABASE|ROLE|MATERIALIZED\s+VIEW)|ALTER\s+(?:TABLE|INDEX|SYSTEM|SESSION|DATABASE|USER|ROLE)|DROP\s+(?:TABLE|INDEX|VIEW|USER|DATABASE|ROLE)|GRANT|REVOKE|VACUUM|REINDEX|ANALYZE|EXPLAIN|TRUNCATE|MERGE\s+INTO|CALL|EXEC(?:UTE)?|COMMIT|ROLLBACK)\b/i;
const PLSQL_RE = /\b(BEGIN\s+\w+|DBMS_\w+|EXEC(?:UTE)?\s+DBMS_)/i;
const DDB_RE = /\b(GetItem|PutItem|Query|Scan|UpdateItem|DeleteItem|BatchWriteItem|BatchGetItem|UpdateTable|DescribeTable|CreateBackup|ExportTableToPointInTime|UpdateContributorInsights)\b/;

function extractQueries(steps: TraceStep[]): ExtractedQuery[] {
  const out: ExtractedQuery[] = [];
  for (const step of steps) {
    const text = step.raw || step.detail || "";
    if (!text) continue;

    // Pull out fenced code blocks first — agents wrap SQL in ```sql ... ```
    const fenceRe = /```(?:sql|plsql|pgsql|psql|tsql|cypher|js|json|text)?\n([\s\S]*?)```/gi;
    let match: RegExpExecArray | null;
    while ((match = fenceRe.exec(text)) !== null) {
      const block = match[1].trim();
      if (!block) continue;
      let lang: ExtractedQuery["language"] = "SQL";
      if (PLSQL_RE.test(block)) lang = "PL/SQL";
      else if (DDB_RE.test(block)) lang = "DynamoDB";
      else if (!SQL_KEYWORD_RE.test(block)) {
        // Skip code blocks that aren't queries (e.g. JSON results without SQL)
        if (!DDB_RE.test(block)) continue;
        lang = "DynamoDB";
      }
      out.push({ language: lang, text: block, source: step.label, timestamp: step.timestamp });
    }

    // Also catch inline SQL hints lines that start with a SQL keyword (no fence)
    const lines = text.split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.length < 20 || trimmed.length > 600) continue;
      if (SQL_KEYWORD_RE.test(trimmed) && !out.some(q => q.text.includes(trimmed))) {
        out.push({ language: PLSQL_RE.test(trimmed) ? "PL/SQL" : "SQL", text: trimmed, source: step.label, timestamp: step.timestamp });
      } else if (DDB_RE.test(trimmed) && !out.some(q => q.text.includes(trimmed))) {
        out.push({ language: "DynamoDB", text: trimmed, source: step.label, timestamp: step.timestamp });
      }
    }
  }
  return out;
}

function timeStr(d: Date) {
  try {
    return d.toLocaleTimeString(undefined, { hour12: false });
  } catch {
    return "";
  }
}

export default function TracePanel({ steps, isVisible, onToggle, sessionId }: TracePanelProps) {
  const [tab, setTab] = useState<Tab>("flow");
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [expandedQueries, setExpandedQueries] = useState<Set<string>>(new Set());

  const queries = useMemo(() => extractQueries(steps), [steps]);

  const toggleExpand = (id: string) => {
    setExpandedNodes(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  useEffect(() => {
    const newNodes: Node[] = steps.map((step, i) => {
      const colors = nodeColors[step.type] || nodeColors.session_start;
      const isExpanded = expandedNodes.has(step.id);
      return {
        id: step.id,
        position: { x: 50, y: i * 110 + 20 },
        data: {
          label: (
            <div style={{ textAlign: "left", fontSize: "11px", lineHeight: "1.4", cursor: "pointer" }} onClick={() => toggleExpand(step.id)}>
              <div style={{ fontWeight: 600, color: colors.text, display: "flex", alignItems: "center", gap: "4px" }}>
                {nodeIcons[step.type]} {step.label}
                <span style={{ fontSize: "8px", opacity: 0.6 }}>{isExpanded ? "▼" : "▶"}</span>
              </div>
              {isExpanded && step.detail && (
                <div style={{ fontSize: "10px", color: "#94a3b8", marginTop: "4px", padding: "4px 6px", background: "rgba(0,0,0,0.3)", borderRadius: "4px" }}>
                  {step.detail}
                </div>
              )}
              {!isExpanded && step.detail && (
                <div style={{ fontSize: "9px", color: "#64748b", marginTop: "2px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "180px" }}>
                  {step.detail}
                </div>
              )}
              {step.duration && (
                <div style={{ fontSize: "9px", color: "#64748b", marginTop: "1px" }}>
                  ⏱ {(step.duration / 1000).toFixed(1)}s
                </div>
              )}
            </div>
          ),
        },
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
        style: {
          background: colors.bg,
          border: `2px solid ${colors.border}`,
          borderRadius: "10px",
          padding: "8px 12px",
          width: 220,
          boxShadow: step.status === "running" ? `0 0 12px ${colors.border}` : "none",
        },
      };
    });

    const newEdges: Edge[] = steps.slice(1).map((step, i) => ({
      id: `e-${steps[i].id}-${step.id}`,
      source: steps[i].id,
      target: step.id,
      animated: step.status === "running",
      style: { stroke: "#475569", strokeWidth: 2 },
      markerEnd: { type: "arrowclosed" as const, color: "#475569" },
    }));

    setNodes(newNodes);
    setEdges(newEdges);
  }, [steps, expandedNodes]);

  if (!isVisible) return null;

  const tabBtn = (id: Tab, label: string, count?: number) => (
    <button
      onClick={() => setTab(id)}
      className={`flex-1 px-3 py-1.5 text-[11px] font-medium border-b-2 transition ${
        tab === id ? "border-blue-500 text-slate-100" : "border-transparent text-slate-400 hover:text-slate-200"
      }`}
    >
      {label}
      {typeof count === "number" && count > 0 && (
        <span className="ml-1.5 inline-flex items-center justify-center rounded-full bg-slate-700 px-1.5 text-[9px] text-slate-300">
          {count}
        </span>
      )}
    </button>
  );

  return (
    <div className="w-80 border-l border-slate-700 bg-slate-950 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">🔍 Session Trace</h3>
          <p className="text-[10px] text-slate-500 mt-0.5 font-mono">{sessionId.slice(0, 24)}</p>
        </div>
        <button onClick={onToggle} className="text-xs text-slate-500 hover:text-slate-300">✕</button>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-slate-800">
        {tabBtn("flow", "Flow", steps.length)}
        {tabBtn("logs", "Logs", steps.length)}
        {tabBtn("queries", "Queries", queries.length)}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {tab === "flow" && (
          <div className="flex-1 overflow-hidden" style={{ minHeight: 400 }}>
            {steps.length === 0 ? (
              <p className="text-xs text-slate-500 text-center mt-12 px-4">
                Click a quick action or send a message to start.<br />
                The flow graph will show each step.
              </p>
            ) : (
              <ReactFlow
                nodes={nodes}
                edges={edges}
                fitView
                fitViewOptions={{ padding: 0.3 }}
                panOnDrag
                zoomOnScroll
                zoomOnPinch
                nodesDraggable={false}
                nodesConnectable={false}
                minZoom={0.3}
                maxZoom={2}
                proOptions={{ hideAttribution: true }}
              >
                <Background color="#1e293b" gap={20} />
                <Controls showInteractive={false} position="bottom-right" />
              </ReactFlow>
            )}
          </div>
        )}

        {tab === "logs" && (
          <div className="flex-1 overflow-y-auto px-3 py-2 scrollbar-thin">
            {steps.length === 0 ? (
              <p className="text-xs text-slate-500 text-center mt-12 px-4">
                No log entries yet. Send a message to populate the log.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {steps.map(step => {
                  const colors = nodeColors[step.type] || nodeColors.session_start;
                  const body = step.raw || step.detail || "";
                  return (
                    <li key={step.id} className="rounded-md border border-slate-800 bg-slate-900/70 overflow-hidden">
                      <div className="flex items-center justify-between gap-2 px-2.5 py-1.5">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="text-[11px]">{nodeIcons[step.type]}</span>
                          <span className="text-[11px] font-medium truncate" style={{ color: colors.text }}>{step.label}</span>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {step.duration && (
                            <span className="text-[9px] text-slate-500">{(step.duration / 1000).toFixed(1)}s</span>
                          )}
                          <span className="text-[9px] text-slate-600 font-mono">{timeStr(step.timestamp)}</span>
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              step.status === "running" ? "bg-yellow-500 animate-pulse"
                              : step.status === "failed" ? "bg-red-500"
                              : "bg-emerald-500"
                            }`}
                          />
                        </div>
                      </div>
                      {body && (
                        <pre className="border-t border-slate-800 bg-slate-950/60 px-2.5 py-1.5 text-[10px] text-slate-400 whitespace-pre-wrap break-words max-h-48 overflow-y-auto scrollbar-thin">
{body}
                        </pre>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}

        {tab === "queries" && (
          <div className="flex-1 overflow-y-auto px-3 py-2 scrollbar-thin">
            {queries.length === 0 ? (
              <p className="text-xs text-slate-500 text-center mt-12 px-4">
                No queries detected yet. SQL, PL/SQL and DynamoDB calls extracted from agent responses will appear here.
              </p>
            ) : (
              <ul className="space-y-2">
                {queries.map((q, i) => {
                  const id = `q-${i}`;
                  const expanded = expandedQueries.has(id);
                  const langColor = q.language === "PL/SQL"
                    ? "text-orange-300 bg-orange-900/30 border-orange-800"
                    : q.language === "DynamoDB"
                    ? "text-yellow-300 bg-yellow-900/30 border-yellow-800"
                    : "text-cyan-300 bg-cyan-900/30 border-cyan-800";
                  return (
                    <li key={id} className="rounded-md border border-slate-800 bg-slate-900/70">
                      <button
                        onClick={() => {
                          setExpandedQueries(prev => {
                            const next = new Set(prev);
                            if (next.has(id)) next.delete(id); else next.add(id);
                            return next;
                          });
                        }}
                        className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 text-left"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold ${langColor}`}>{q.language}</span>
                          <span className="text-[11px] text-slate-300 truncate font-mono">{q.text.split("\n")[0]}</span>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <span className="text-[9px] text-slate-600 font-mono">{timeStr(q.timestamp)}</span>
                          <span className="text-[10px] text-slate-500">{expanded ? "▼" : "▶"}</span>
                        </div>
                      </button>
                      {expanded && (
                        <div className="border-t border-slate-800 bg-slate-950/60">
                          <div className="px-2.5 pt-1 text-[9px] text-slate-500">from: {q.source}</div>
                          <pre className="px-2.5 py-1.5 text-[10px] text-slate-300 font-mono whitespace-pre-wrap break-words max-h-72 overflow-y-auto scrollbar-thin">
{q.text}
                          </pre>
                          <div className="flex justify-end px-2.5 pb-1.5">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                navigator.clipboard?.writeText(q.text);
                              }}
                              className="text-[10px] text-slate-500 hover:text-slate-200"
                            >
                              📋 Copy
                            </button>
                          </div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
