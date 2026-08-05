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

import type { GatingState } from "@/lib/dba/types";

// Shown instead of the GraphPane when gating_state != approved (R6.8, R10.4).
// States the current state and explains the capability is gated — never a
// fault-implying error. `pending` and `not_approved` are intentional gates;
// `null` means the gate config is unavailable (fail-closed), still framed as
// a capability-gated state rather than a system error.
const COPY: Record<string, { title: string; body: string }> = {
  pending: {
    title: "Knowledge graph is pending activation",
    body: "The DBA knowledge graph is provisioned but not yet turned on for this account. The static schema is available; live traversal and the timeline begin once an administrator approves the capability.",
  },
  not_approved: {
    title: "Knowledge graph is not enabled",
    body: "This capability is intentionally withheld for this account. No graph data is ingested or served while it is not approved.",
  },
  unavailable: {
    title: "Knowledge graph gating is unavailable",
    body: "The gating configuration could not be resolved, so the capability is held closed. This is a configuration state, not a runtime fault — graph data is not served until gating reads cleanly as approved.",
  },
};

export default function GatingNotice({ state }: { state: GatingState }) {
  const key = state === null ? "unavailable" : state;
  const copy = COPY[key] ?? COPY.unavailable;
  return (
    <div className="flex h-full min-h-[320px] flex-col items-center justify-center rounded-lg border border-slate-800 bg-slate-900/40 p-8 text-center">
      <div className="mb-3 text-3xl">🔒</div>
      <h2 className="text-lg font-semibold text-slate-200">{copy.title}</h2>
      <p className="mt-2 max-w-xl text-sm text-slate-400">{copy.body}</p>
      <span className="mt-4 rounded border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-400">
        gating_state: {state ?? "unavailable"}
      </span>
    </div>
  );
}
