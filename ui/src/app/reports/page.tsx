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

import { useCallback, useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar";
import GamificationBar from "@/components/GamificationBar";

interface ReportRun {
  db_identifier: string;
  report_run_id: string;
  engine: string;
  cadence: string;
  generated_at: string;
  s3_prefix: string;
  md_sha256: string;
  status: "success" | "partial" | "failed";
  section_failures: string[];
}

interface GenerateResponse {
  run_id: string;
  status: "success" | "partial" | "failed";
  section_failures: string[];
  markdown: string;
  engine: string;
  cadence: string;
  generated_at: string;
}

const DB_OPTIONS = [
  { id: "database-test", engine: "postgresql", label: "Aurora PG (database-test)" },
  { id: "dbops-aurora-mysql", engine: "mysql", label: "Aurora MySQL (Prod)" },
  { id: "oracle-prod", engine: "oracle", label: "Oracle EE 19c (Prod)" },
  { id: "dbops-orders", engine: "dynamodb", label: "DynamoDB Orders" },
];

export default function ReportsPage() {
  const [selectedAgent, setSelectedAgent] = useState("postgresql");
  const [selectedDb, setSelectedDb] = useState(DB_OPTIONS[0].id);
  const [runs, setRuns] = useState<ReportRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeRun, setActiveRun] = useState<GenerateResponse | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/reports?db=${encodeURIComponent(selectedDb)}`);
      if (res.ok) {
        const data = (await res.json()) as { runs: ReportRun[] };
        setRuns(data.runs ?? []);
      } else {
        setRuns([]);
      }
    } finally {
      setLoading(false);
    }
  }, [selectedDb]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const generateNow = useCallback(async () => {
    setLoading(true);
    try {
      const engine = DB_OPTIONS.find((d) => d.id === selectedDb)?.engine ?? "postgresql";
      const res = await fetch("/api/reports/generate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ db_identifier: selectedDb, engine, cadence: "manual" }),
      });
      if (res.ok) {
        const data = (await res.json()) as GenerateResponse;
        setActiveRun(data);
      }
      refresh();
    } finally {
      setLoading(false);
    }
  }, [selectedDb, refresh]);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar selectedAgent={selectedAgent} onSelectAgent={setSelectedAgent} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <GamificationBar />
        <div className="flex flex-1 overflow-hidden">
          {/* Left: db picker + run list */}
          <aside className="w-80 flex-shrink-0 overflow-y-auto border-r border-slate-700 bg-slate-900/50 p-4">
            <h2 className="mb-3 text-sm font-semibold text-slate-400 uppercase tracking-wider">
              Reports
            </h2>
            <label className="text-xs text-slate-400">Database</label>
            <select
              value={selectedDb}
              onChange={(e) => setSelectedDb(e.target.value)}
              className="mt-1 w-full rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200"
            >
              {DB_OPTIONS.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
            <button
              onClick={generateNow}
              disabled={loading}
              className="mt-3 w-full rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-40"
            >
              {loading ? "Working…" : "Generate Now"}
            </button>

            <h3 className="mt-6 mb-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Prior runs
            </h3>
            {runs.length === 0 ? (
              <p className="text-[11px] text-slate-500">
                No runs yet. Click <strong>Generate Now</strong>.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {runs.map((r) => (
                  <li
                    key={r.report_run_id}
                    className="rounded border border-slate-800 bg-slate-900/70 p-2 text-[11px]"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-slate-300">{r.report_run_id}</span>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[9px] font-semibold ${
                          r.status === "success"
                            ? "bg-emerald-900/40 text-emerald-300"
                            : r.status === "partial"
                              ? "bg-amber-900/40 text-amber-300"
                              : "bg-rose-900/40 text-rose-300"
                        }`}
                      >
                        {r.status}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-slate-500">{r.generated_at}</div>
                    <div className="mt-0.5 text-[10px] text-slate-600">
                      {r.engine} · {r.cadence}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </aside>

          {/* Main: rendered report */}
          <main className="flex-1 overflow-y-auto p-6">
            {!activeRun ? (
              <div className="text-sm text-slate-500">
                Click <strong>Generate Now</strong> to render a report. Prior runs appear in the
                left panel.
              </div>
            ) : (
              <article className="prose prose-invert max-w-none">
                <div className="mb-4 flex items-center gap-2">
                  <span
                    className={`rounded px-2 py-0.5 text-[10px] font-semibold ${
                      activeRun.status === "success"
                        ? "bg-emerald-900/40 text-emerald-300"
                        : activeRun.status === "partial"
                          ? "bg-amber-900/40 text-amber-300"
                          : "bg-rose-900/40 text-rose-300"
                    }`}
                  >
                    {activeRun.status}
                  </span>
                  <span className="text-[11px] text-slate-500 font-mono">
                    {activeRun.run_id}
                  </span>
                </div>
                <pre className="whitespace-pre-wrap rounded border border-slate-800 bg-slate-950/60 p-4 text-[12px] text-slate-200">
                  {activeRun.markdown}
                </pre>
              </article>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
