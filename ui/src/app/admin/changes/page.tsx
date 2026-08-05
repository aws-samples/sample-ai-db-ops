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
import { withUserHeader } from "@/lib/auth/client";

interface ChangeEvent {
  event_id: string;
  source: "git" | "cloudtrail" | "agent" | "database";
  actor: string;
  timestamp: string;
  engine: "postgresql" | "mysql" | "oracle" | "dynamodb" | null;
  resource_id: string;
  severity: "low" | "medium" | "high" | "critical";
  summary: string;
  details_url: string;
  raw_payload_ref: string;
}

interface FeedResponse {
  events: ChangeEvent[];
  page: number;
  total_pages: number;
}

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

const ENGINE_ICON: Record<string, string> = {
  postgresql: "🐘",
  mysql: "🐬",
  oracle: "🦅",
  dynamodb: "⚡",
};

const ALL_SOURCES = ["git", "cloudtrail", "agent", "database"];
const ALL_SEVERITIES = ["low", "medium", "high", "critical"];
const ALL_ENGINES = ["postgresql", "mysql", "oracle", "dynamodb"];

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded border px-2 py-0.5 text-[11px] ${
        active
          ? "border-blue-500 bg-blue-950/50 text-blue-200"
          : "border-slate-700 text-slate-400 hover:bg-slate-800"
      }`}
    >
      {label}
    </button>
  );
}

export default function ChangeFeedPage() {
  const [data, setData] = useState<FeedResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [sources, setSources] = useState<string[]>([]);
  const [severities, setSeverities] = useState<string[]>([]);
  const [engines, setEngines] = useState<string[]>([]);

  const toggle = (
    list: string[],
    setList: (v: string[]) => void,
    value: string,
  ) => {
    setPage(1);
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (sources.length) params.set("source", sources.join(","));
    if (severities.length) params.set("severity", severities.join(","));
    if (engines.length) params.set("engine", engines.join(","));
    params.set("page", String(page));
    params.set("page_size", "25");
    try {
      const res = await fetch(`/api/admin/changes?${params.toString()}`, {
        headers: withUserHeader(),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body?.error || `request failed (${res.status})`);
        setData(null);
      } else {
        setData(body as FeedResponse);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [sources, severities, engines, page]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-semibold">Change Feed</h1>
        <p className="mt-1 text-xs text-slate-400">
          Every change that alters a SQL query or database infrastructure,
          aggregated from Git commits, CloudTrail, agent Tier-3 actions, and
          live database DDL (ALTER / TRUNCATE / CREATE / DROP captured from
          Postgres logs via CloudWatch) into one chronological, filterable
          audit trail. Read-only.
        </p>
      </header>

      {/* Filters */}
      <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-900/40 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-16 text-[11px] uppercase text-slate-500">Source</span>
          {ALL_SOURCES.map((s) => (
            <Chip key={s} label={s} active={sources.includes(s)} onClick={() => toggle(sources, setSources, s)} />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-16 text-[11px] uppercase text-slate-500">Severity</span>
          {ALL_SEVERITIES.map((s) => (
            <Chip key={s} label={s} active={severities.includes(s)} onClick={() => toggle(severities, setSeverities, s)} />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-16 text-[11px] uppercase text-slate-500">Engine</span>
          {ALL_ENGINES.map((s) => (
            <Chip key={s} label={s} active={engines.includes(s)} onClick={() => toggle(engines, setEngines, s)} />
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-200">
          <strong>Error:</strong> {error}
        </div>
      )}

      {loading && <p className="text-sm text-slate-500">Loading…</p>}

      {data && data.events.length === 0 && !loading && (
        <p className="text-sm text-slate-500">
          No change events match the current filters.
        </p>
      )}

      {data && data.events.length > 0 && (
        <>
          <table className="w-full border border-slate-800 text-sm">
            <thead className="bg-slate-900/60 text-[11px] uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2 text-left">When (UTC)</th>
                <th className="px-3 py-2 text-left">Source</th>
                <th className="px-3 py-2 text-left">Sev</th>
                <th className="px-3 py-2 text-left">Engine</th>
                <th className="px-3 py-2 text-left">Change</th>
                <th className="px-3 py-2 text-left">Link</th>
              </tr>
            </thead>
            <tbody>
              {data.events.map((e) => (
                <tr key={e.event_id} className="border-t border-slate-800 hover:bg-slate-900/40 align-top">
                  <td className="px-3 py-2 whitespace-nowrap text-slate-400">
                    {e.timestamp.replace("T", " ").slice(0, 16)}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${SOURCE_BADGE[e.source]}`}>
                      {e.source}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${SEVERITY_BADGE[e.severity]}`}>
                      {e.severity}
                    </span>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-slate-300">
                    {e.engine ? `${ENGINE_ICON[e.engine] ?? ""} ${e.engine}` : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <div className="text-slate-200">{e.summary}</div>
                    <div className="text-[11px] font-mono text-slate-500">{e.resource_id}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {e.details_url.startsWith("http") ? (
                      <a href={e.details_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300 text-[11px]">
                        source ↗
                      </a>
                    ) : (
                      <span className="text-[11px] text-slate-600">{e.raw_payload_ref}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>
              Page {data.page} of {data.total_pages}
            </span>
            <div className="flex gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="rounded border border-slate-700 px-3 py-1 disabled:opacity-40 hover:bg-slate-800"
              >
                ← Prev
              </button>
              <button
                disabled={data.page >= data.total_pages}
                onClick={() => setPage((p) => p + 1)}
                className="rounded border border-slate-700 px-3 py-1 disabled:opacity-40 hover:bg-slate-800"
              >
                Next →
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
