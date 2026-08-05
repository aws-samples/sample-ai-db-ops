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

// Properties for a non-ChangeEvent node + a "re-center" action triggering a
// fresh /api/dba/graph traversal focused on that node (R6.7).
export default function NodeDetailDrawer({
  node,
  onRecenter,
  onClose,
}: {
  node: GraphNode | null;
  onRecenter: (nodeId: string) => void;
  onClose: () => void;
}) {
  if (!node) return null;
  const entries = Object.entries(node.props);
  return (
    <div className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-slate-800 bg-slate-950 shadow-2xl">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-200">{node.type}</h3>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-200">
          ✕
        </button>
      </div>
      <div className="space-y-4 p-4">
        <p className="text-sm text-slate-200">{node.label}</p>
        <dl className="space-y-1 text-xs">
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-slate-500">node_id</dt>
            <dd className="min-w-0 break-words font-mono text-slate-300">{node.node_id}</dd>
          </div>
          {entries.map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="w-24 shrink-0 text-slate-500">{k}</dt>
              <dd className="min-w-0 break-words font-mono text-slate-300">{String(v)}</dd>
            </div>
          ))}
        </dl>
        <button
          onClick={() => onRecenter(node.node_id)}
          className="rounded border border-blue-700 bg-blue-950/50 px-3 py-1.5 text-xs text-blue-200 hover:bg-blue-900/50"
        >
          Re-center graph here
        </button>
      </div>
    </div>
  );
}
