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

// Normalized ChangeEvent record + click-through to the underlying source
// resolved at runtime (R6.6, R8.2). No embedded account or resource id — the
// details_url comes from the event payload (config/env-resolved server-side).
export default function EventDetailDrawer({
  event,
  onClose,
}: {
  event: ChangeEvent | null;
  onClose: () => void;
}) {
  if (!event) return null;
  const rows: [string, string][] = [
    ["Event ID", event.event_id],
    ["Source", event.source],
    ["Actor", event.actor],
    ["When (UTC)", event.timestamp],
    ["Engine", event.engine ?? "—"],
    ["Resource", event.resource_id],
    ["Severity", event.severity],
  ];
  const isLink = event.details_url.startsWith("http");
  return (
    <div className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-slate-800 bg-slate-950 shadow-2xl">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-200">Change Event</h3>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-200">
          ✕
        </button>
      </div>
      <div className="space-y-4 p-4">
        <p className="text-sm text-slate-200">{event.summary}</p>
        <dl className="space-y-1 text-xs">
          {rows.map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="w-24 shrink-0 text-slate-500">{k}</dt>
              <dd className="min-w-0 break-words font-mono text-slate-300">{v}</dd>
            </div>
          ))}
        </dl>
        <div>
          {isLink ? (
            <a
              href={event.details_url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300"
            >
              Open source ↗
            </a>
          ) : (
            <span className="font-mono text-[11px] text-slate-500">
              {event.details_url}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
