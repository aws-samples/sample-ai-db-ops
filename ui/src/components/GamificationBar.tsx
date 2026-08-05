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

import Link from "next/link";

export default function GamificationBar({ onToggleTrace }: { onToggleTrace?: () => void }) {
  const xp = 4275;
  const maxXp = 5000;
  const pct = Math.round((xp / maxXp) * 100);

  return (
    <header className="flex items-center justify-between border-b border-slate-700 bg-slate-900 px-6 py-3">
      {/* Left — Title */}
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-bold">🎮 DB Ops Command Center</h1>
      </div>

      {/* Center — spacer */}
      <div className="flex-1" />

      {/* Right — Nav + User */}
      <div className="flex items-center gap-2">
        <Link
          href="/admin/changes"
          className="rounded-lg bg-slate-800 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700"
          title="Change Feed — DB & SQL change audit trail"
        >
          🔐 Change Feed
        </Link>
        <Link
          href="/reports"
          className="rounded-lg bg-slate-800 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700"
          title="Database health reports"
        >
          📈 Reports
        </Link>
        <Link
          href="/admin"
          className="rounded-lg bg-slate-800 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700"
          title="Admin console"
        >
          🛠️ Admin
        </Link>
        <Link
          href="/dba"
          className="rounded-lg bg-slate-800 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700"
          title="DBA Knowledge Graph — single pane of every change"
        >
          🧭 DBA View
        </Link>
        <button onClick={onToggleTrace} className="rounded-lg bg-slate-800 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700">
          🔍 Trace
        </button>
        <div className="h-8 w-8 rounded-full bg-blue-600 flex items-center justify-center text-xs font-bold" title={process.env.NEXT_PUBLIC_USER_ID || "dbops-user"}>
          {(process.env.NEXT_PUBLIC_USER_ID || "dbops-user").slice(0, 2).toUpperCase()}
        </div>
      </div>
    </header>
  );
}
