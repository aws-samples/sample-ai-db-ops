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

import { useState } from "react";
import type { ChangeEvent } from "@/lib/dba/types";
import ChangeEventRow from "./ChangeEventRow";

const PAGE_SIZE = 50;

// Reverse-chronological ChangeEvents, 50/page (R6.2). The parent passes the
// already-filtered, already-ordered list; this pane only paginates locally and
// raises row clicks to open the EventDetailDrawer.
export default function TimelinePane({
  events,
  onSelect,
}: {
  events: ChangeEvent[];
  onSelect: (e: ChangeEvent) => void;
}) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(events.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PAGE_SIZE;
  const rows = events.slice(start, start + PAGE_SIZE);

  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800 bg-slate-900/40">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <h3 className="text-sm font-semibold text-slate-200">Timeline</h3>
        <span className="text-[11px] text-slate-500">{events.length} events</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 ? (
          <p className="px-3 py-6 text-sm text-slate-500">
            No change events match the current filters.
          </p>
        ) : (
          rows.map((e) => <ChangeEventRow key={e.event_id} event={e} onClick={onSelect} />)
        )}
      </div>
      {events.length > PAGE_SIZE && (
        <div className="flex items-center justify-between border-t border-slate-800 px-3 py-2 text-xs text-slate-400">
          <span>
            Page {safePage} of {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800 disabled:opacity-40"
            >
              ← Prev
            </button>
            <button
              disabled={safePage >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800 disabled:opacity-40"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
