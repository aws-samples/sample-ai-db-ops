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

import type { ChangeEvent } from "@/lib/dba/types";
import { ddlKind } from "@/lib/dba/filters";

const SOURCE_BADGE: Record<string, string> = {
  git: "bg-violet-900/40 text-violet-300 border-violet-800",
  cloudtrail: "bg-sky-900/40 text-sky-300 border-sky-800",
  agent: "bg-teal-900/40 text-teal-300 border-teal-800",
  database: "bg-emerald-900/40 text-emerald-300 border-emerald-800",
};

const SEVERITY_BADGE: Record<string, string> = {
  low: "bg-slate-800 text-slate-300 border-slate-700",
  medium: "bg-amber-900/40 text-amber-300 border-amber-800",
  high: "bg-orange-900/40 text-orange-300 border-orange-800",
  critical: "bg-rose-900/40 text-rose-300 border-rose-800",
};

// One timeline row; click opens the EventDetailDrawer (R6.2, R6.6).
export default function ChangeEventRow({
  event,
  onClick,
}: {
  event: ChangeEvent;
  onClick: (e: ChangeEvent) => void;
}) {
  const kind = ddlKind(event);
  return (
    <button
      onClick={() => onClick(event)}
      className="flex w-full items-start gap-3 border-t border-slate-800 px-3 py-2 text-left hover:bg-slate-900/40"
    >
      <span className="w-28 shrink-0 whitespace-nowrap text-[11px] text-slate-400">
        {event.timestamp.replace("T", " ").slice(0, 16)}
      </span>
      <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${SOURCE_BADGE[event.source]}`}>
        {event.source}
      </span>
      <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${SEVERITY_BADGE[event.severity]}`}>
        {event.severity}
      </span>
      {kind && (
        <span className="shrink-0 rounded border border-indigo-800 bg-indigo-950/50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-300">
          {kind}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-slate-200">{event.summary}</span>
        <span className="block truncate font-mono text-[11px] text-slate-500">
          {event.actor} · {event.resource_id}
        </span>
      </span>
    </button>
  );
}
