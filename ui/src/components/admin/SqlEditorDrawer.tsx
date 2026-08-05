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
import CodeMirror from "@uiw/react-codemirror";
import { sql, MySQL, PostgreSQL } from "@codemirror/lang-sql";
import { json } from "@codemirror/lang-json";
import { withUserHeader } from "@/lib/auth/client";

export type Engine = "postgresql" | "mysql" | "oracle" | "dynamodb";
export type Tier = "tier_1_read" | "tier_2_advise" | "tier_3_act";

interface Classification {
  tier: Tier;
  leading_keyword: string | null;
  reason: string;
}

interface RunResult {
  tier: Tier;
  leading_keyword: string | null;
  reason: string;
  rows: Record<string, unknown>[] | null;
  rowcount: number | null;
  forwarded_to_agent: boolean;
}

interface SqlEditorDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  engine: Engine;
  initialBody?: string;
  /**
   * Optional dialect override. Defaults inferred from `engine`.
   */
  title?: string;
}

const TIER_BADGE: Record<Tier, { label: string; className: string }> = {
  tier_1_read: { label: "Tier 1 — read", className: "bg-emerald-900/40 text-emerald-300 border-emerald-800" },
  tier_2_advise: { label: "Tier 2 — advise", className: "bg-amber-900/40 text-amber-300 border-amber-800" },
  tier_3_act: { label: "Tier 3 — act", className: "bg-rose-900/40 text-rose-300 border-rose-800" },
};

function languageExtension(engine: Engine) {
  if (engine === "postgresql") return sql({ dialect: PostgreSQL });
  if (engine === "mysql") return sql({ dialect: MySQL });
  if (engine === "dynamodb") return json();
  return sql();
}

export default function SqlEditorDrawer({
  isOpen,
  onClose,
  engine,
  initialBody = "",
  title,
}: SqlEditorDrawerProps) {
  const [body, setBody] = useState(initialBody);
  const [classification, setClassification] = useState<Classification | null>(null);
  const [classifyError, setClassifyError] = useState<string | null>(null);
  const [applyToken, setApplyToken] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  // Refresh body if the parent passes a new initialBody (e.g. user clicks
  // a different Custom_Button while drawer is open).
  useEffect(() => {
    setBody(initialBody);
    setClassification(null);
    setResult(null);
    setRunError(null);
    setApplyToken("");
  }, [initialBody, isOpen]);

  // Live classify on each parsable edit (debounced to ~250ms).
  useEffect(() => {
    if (!isOpen || !body.trim()) {
      setClassification(null);
      setClassifyError(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const res = await fetch("/api/admin/sql/classify", {
          method: "POST",
          headers: withUserHeader({ "content-type": "application/json" }),
          body: JSON.stringify({ engine, body }),
        });
        const data = (await res.json()) as Classification | { error: string };
        if ("error" in data) {
          setClassifyError(data.error);
          setClassification(null);
        } else {
          setClassification(data);
          setClassifyError(null);
        }
      } catch (err) {
        setClassifyError(err instanceof Error ? err.message : String(err));
      }
    }, 250);
    return () => clearTimeout(t);
  }, [body, engine, isOpen]);

  const tier = classification?.tier ?? null;
  const isTier3 = tier === "tier_3_act";
  const applyEnabled =
    !running &&
    classification !== null &&
    !classifyError &&
    body.trim().length > 0 &&
    (!isTier3 || applyToken === "APPLY");

  const onApply = useCallback(async () => {
    setRunning(true);
    setResult(null);
    setRunError(null);
    try {
      const res = await fetch("/api/admin/sql/run", {
        method: "POST",
        headers: withUserHeader({ "content-type": "application/json" }),
        body: JSON.stringify({
          engine,
          body,
          apply_token: isTier3 ? applyToken : null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setRunError(
          (data && (data.error || data.detail)) || `request failed (${res.status})`,
        );
      } else {
        setResult(data as RunResult);
      }
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }, [engine, body, isTier3, applyToken]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50">
      <aside
        className="flex h-full w-[720px] max-w-full flex-col bg-slate-950 border-l border-slate-700 shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        <header className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-100">
              {title ?? "Run SQL"}
            </h2>
            <p className="text-[11px] text-slate-500 mt-0.5">
              Engine: <span className="font-mono">{engine}</span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800"
          >
            Close
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {/* Editor */}
          <div className="rounded-lg border border-slate-700 overflow-hidden">
            <CodeMirror
              value={body}
              height="220px"
              theme="dark"
              extensions={[languageExtension(engine)]}
              onChange={setBody}
              basicSetup={{ lineNumbers: true, foldGutter: true }}
            />
          </div>

          {/* Tier badge / classification feedback */}
          <div className="flex items-center gap-2 text-[11px]">
            {classification ? (
              <span
                className={`rounded border px-2 py-0.5 font-semibold ${TIER_BADGE[classification.tier].className}`}
              >
                {TIER_BADGE[classification.tier].label}
              </span>
            ) : (
              <span className="text-slate-500">Classification…</span>
            )}
            {classification?.leading_keyword && (
              <span className="text-slate-500">
                leading: <span className="font-mono">{classification.leading_keyword}</span>
              </span>
            )}
            {classifyError && (
              <span className="text-rose-400">classify error: {classifyError}</span>
            )}
          </div>

          {/* Tier 3 confirmation gate */}
          {isTier3 && (
            <div className="rounded-lg border border-rose-800 bg-rose-950/20 p-3">
              <p className="text-[12px] text-rose-200">
                This is a <strong>Tier 3</strong> action. Type{" "}
                <code className="font-mono bg-rose-900/40 px-1 py-0.5 rounded">APPLY</code>{" "}
                to confirm. The agent gates this independently: the Tier 3 tool call
                halts for explicit approval before it executes.
              </p>
              <input
                type="text"
                value={applyToken}
                onChange={(e) => setApplyToken(e.target.value)}
                placeholder="Type APPLY"
                className="mt-2 w-full rounded border border-rose-800 bg-rose-950/40 px-3 py-2 text-sm text-rose-200 placeholder-rose-500 focus:outline-none focus:ring-1 focus:ring-rose-500"
              />
            </div>
          )}

          {/* Apply / Cancel */}
          <div className="flex items-center justify-end gap-2">
            <button
              onClick={onClose}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              onClick={onApply}
              disabled={!applyEnabled}
              className="rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {running ? "Running…" : "Apply"}
            </button>
          </div>

          {/* Result panel */}
          {runError && (
            <div className="rounded-lg border border-rose-800 bg-rose-950/30 p-3 text-[12px] text-rose-200">
              <strong>Error:</strong> {runError}
            </div>
          )}
          {result && (
            <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-3 text-[12px] text-slate-200">
              <div className="mb-2 flex items-center gap-2 text-[11px] text-slate-400">
                <span>tier: {result.tier}</span>
                {result.forwarded_to_agent && (
                  <span className="text-blue-400">forwarded to agent</span>
                )}
                {result.rowcount !== null && (
                  <span>rowcount: {result.rowcount}</span>
                )}
                {result.rows && (
                  <span>rows: {result.rows.length}</span>
                )}
              </div>
              {result.rows && result.rows.length > 0 && (
                <div className="overflow-auto max-h-72 border border-slate-800 rounded">
                  <table className="text-[11px] w-full">
                    <thead className="bg-slate-800/60 sticky top-0">
                      <tr>
                        {Object.keys(result.rows[0]).map((k) => (
                          <th key={k} className="px-2 py-1 text-left font-semibold text-slate-300">
                            {k}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.slice(0, 200).map((row, i) => (
                        <tr key={i} className="border-t border-slate-800">
                          {Object.values(row).map((v, j) => (
                            <td key={j} className="px-2 py-1 font-mono text-slate-300">
                              {v === null ? "—" : String(v)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
