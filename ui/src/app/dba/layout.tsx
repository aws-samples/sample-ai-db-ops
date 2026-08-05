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

import Link from "next/link";

export const metadata = {
  title: "DBOps — DBA Knowledge Graph",
};

// Top-level /dba area — the DBA View, distinct from the app-team screens.
// Its own nav entry and a gating_state badge shown on every screen (R1.1,
// R1.7). The badge value is rendered client-side by the GraphExplorer once it
// learns the state from /api/kg/health; the layout reserves the slot.
export default function DbaViewLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/60 px-6 py-3">
        <nav className="flex items-center gap-6 text-sm">
          <Link href="/dba" className="font-semibold tracking-wide text-slate-100">
            🧭 DBA Knowledge Graph
          </Link>
          <span className="text-xs text-slate-500">
            Single pane of every change across the fleet — read-only
          </span>
          <span className="ml-auto text-xs text-slate-500">
            <Link href="/" className="hover:text-slate-300">
              ← Back to fleet
            </Link>
          </span>
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
    </div>
  );
}
