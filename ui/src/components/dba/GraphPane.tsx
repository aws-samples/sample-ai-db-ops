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

import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphResult, GraphNode } from "@/lib/dba/types";

// Node-link visualization with React Flow (R6.1, R5.6). Nodes are colored by
// GraphNode.type; clicking a node raises onNodeClick so the parent can expand
// one hop or re-center via /api/dba/node/:id (R6.7).

const TYPE_COLOR: Record<string, string> = {
  ChangeEvent: "#6366f1", // indigo
  Principal: "#14b8a6", // teal
  Database: "#3b82f6", // blue
  Table: "#0ea5e9", // sky
  Account: "#64748b", // slate
  Ticket: "#f59e0b", // amber
  Agent: "#a855f7", // purple
  Tool: "#8b5cf6", // violet
  Template: "#10b981", // emerald
  Incident: "#ef4444", // red
};

// Deterministic radial layout: focus at center, others on a ring by index.
function layout(graph: GraphResult): { nodes: Node[]; edges: Edge[] } {
  const others = graph.nodes.filter((n) => n.node_id !== graph.focus);
  const radius = Math.max(180, others.length * 26);
  const cx = 380;
  const cy = 260;

  const positioned = new Map<string, { x: number; y: number }>();
  positioned.set(graph.focus, { x: cx, y: cy });
  others.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, others.length);
    positioned.set(n.node_id, {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    });
  });

  const nodes: Node[] = graph.nodes.map((n: GraphNode) => {
    const pos = positioned.get(n.node_id) ?? { x: cx, y: cy };
    const isFocus = n.node_id === graph.focus;
    const color = TYPE_COLOR[n.type] ?? "#64748b";
    return {
      id: n.node_id,
      position: pos,
      data: { label: `${n.type}\n${n.label}` },
      style: {
        background: color,
        color: "#0f172a",
        border: isFocus ? "3px solid #f1f5f9" : "1px solid #1e293b",
        borderRadius: 8,
        fontSize: 10,
        fontWeight: 600,
        padding: 6,
        width: 150,
        whiteSpace: "pre-line",
        textAlign: "center",
      },
    };
  });

  const edges: Edge[] = graph.edges.map((e, i) => ({
    id: `${e.source_id}|${e.edge_type}|${e.target_id}|${i}`,
    source: e.source_id,
    target: e.target_id,
    label: e.edge_type,
    labelStyle: { fontSize: 9, fill: "#94a3b8" },
    style: { stroke: "#475569" },
    animated: e.edge_type === "CAUSED_BY",
  }));

  return { nodes, edges };
}

export default function GraphPane({
  graph,
  onNodeClick,
}: {
  graph: GraphResult | null;
  onNodeClick: (nodeId: string) => void;
}) {
  const { nodes, edges } = useMemo(
    () => (graph ? layout(graph) : { nodes: [], edges: [] }),
    [graph],
  );

  return (
    <div className="h-full w-full rounded-lg border border-slate-800 bg-slate-900/40">
      {!graph || graph.nodes.length === 0 ? (
        <div className="flex h-full min-h-[320px] items-center justify-center text-sm text-slate-500">
          Select a node from the timeline to explore its connections.
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          onNodeClick={(_, node) => onNodeClick(node.id)}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1e293b" gap={20} />
          <Controls showInteractive={false} />
        </ReactFlow>
      )}
    </div>
  );
}
