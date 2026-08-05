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

import type { GraphNode } from "@/lib/dba/types";

// High-severity DDL with no ticket from /api/dba/unticketed (R7.4). The route
// returns GraphNode objects (ChangeEvent nodes), so we render from the node
// shape: `label` is the change summary and `props.timestamp` is the time.
// Shows a "may be incomplete" banner when complete = false.

function nodeTimestamp(n: GraphNode): string {
  const raw = (n.props?.timestamp ?? n.props?.contributing_ts) as string | undefined;
  if (!raw) return "—";
  return String(raw).replace("T", " ").slice(0, 16);
}

export default function UnticketedPanel({
  events,
  complete,
  onSelect,
}: {
  events: GraphNode[];
  complete: boolean;
  onSelect: (node: GraphNode) => void;
}) {
  return (
    <div className="rounded-lg border border-rose-900/60 bg-rose-950/20">
      <div className="flex items-center justify-between border-b border-rose-900/60 px-3 py-2">
        <h3 className="text-sm font-semibold text-rose-200">
          ⚠️ Unticketed high-severity DDL
        </h3>
        <span className="text-[11px] text-rose-300/70">{events.length}</span>
      </div>
      {!complete && (
        <p className="border-b border-rose-900/40 bg-amber-950/30 px-3 py-1.5 text-[11px] text-amber-300">
          This list may be incomplete — recent ingestion may still be catching up.
        </p>
      )}
      <div className="max-h-48 overflow-y-auto">
        {events.length === 0 ? (
          <p className="px-3 py-3 text-xs text-slate-500">
            No unticketed high-severity DDL in the window. Every risky change is
            accounted for.
          </p>
        ) : (
          events.map((n) => (
            <button
              key={n.node_id}
              onClick={() => onSelect(n)}
              className="flex w-full items-start gap-2 border-t border-rose-900/30 px-3 py-1.5 text-left hover:bg-rose-950/40"
            >
              <span className="w-24 shrink-0 text-[11px] text-slate-400">
                {nodeTimestamp(n)}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs text-slate-200">
                {n.label}
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
