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
import type { Engine } from "./SqlEditorDrawer";
import { withUserHeader } from "@/lib/auth/client";

interface CustomButtonModalProps {
  isOpen: boolean;
  onClose: () => void;
  engine: Engine;
  onCreated: () => void;
}

export default function CustomButtonModal({
  isOpen,
  onClose,
  engine,
  onCreated,
}: CustomButtonModalProps) {
  const [label, setLabel] = useState("");
  const [icon, setIcon] = useState("");
  const [bodyKind, setBodyKind] = useState<"sql" | "prompt">("sql");
  const [body, setBody] = useState("");
  const [tierHint, setTierHint] = useState<1 | 2 | 3>(1);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/admin/buttons", {
        method: "POST",
        headers: withUserHeader({ "content-type": "application/json" }),
        credentials: "include",
        body: JSON.stringify({
          label,
          icon,
          engine,
          target_scope: "",
          body_kind: bodyKind,
          body,
          tier_hint: tierHint,
          confirmation_required: tierHint === 3,
        }),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as {
          error?: string;
          detail?: string;
        };
        setError(data.error || data.detail || `request failed (${res.status})`);
        return;
      }
      // Reset and close.
      setLabel("");
      setIcon("");
      setBody("");
      setBodyKind("sql");
      setTierHint(1);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const valid = label.trim().length > 0 && body.trim().length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-[560px] max-h-[85vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-700 px-6 py-4">
          <h2 className="text-base font-semibold">Create Custom Button</h2>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-800">
            ✕
          </button>
        </div>

        <div className="px-6 py-4 space-y-3 text-sm">
          <div className="grid grid-cols-[1fr_120px] gap-3">
            <div>
              <label className="text-xs text-slate-400">Label *</label>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                maxLength={40}
                placeholder="e.g. Slow Queries (last hour)"
                className="mt-1 w-full rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400">Icon</label>
              <input
                value={icon}
                onChange={(e) => setIcon(e.target.value)}
                maxLength={4}
                placeholder="🐢"
                className="mt-1 w-full rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-slate-400">Engine</label>
            <input
              value={engine}
              disabled
              className="mt-1 w-full rounded border border-slate-700 bg-slate-800/50 px-3 py-1.5 text-sm text-slate-500"
            />
          </div>

          <div>
            <label className="text-xs text-slate-400">Body kind</label>
            <div className="mt-1 flex gap-2">
              <button
                onClick={() => setBodyKind("sql")}
                className={`rounded px-3 py-1 text-xs ${
                  bodyKind === "sql"
                    ? "bg-blue-600 text-white"
                    : "bg-slate-800 text-slate-400 border border-slate-600"
                }`}
              >
                SQL
              </button>
              <button
                onClick={() => setBodyKind("prompt")}
                className={`rounded px-3 py-1 text-xs ${
                  bodyKind === "prompt"
                    ? "bg-blue-600 text-white"
                    : "bg-slate-800 text-slate-400 border border-slate-600"
                }`}
              >
                Prompt
              </button>
            </div>
          </div>

          <div>
            <label className="text-xs text-slate-400">
              {bodyKind === "sql" ? "SQL body *" : "Prompt body *"}
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={6}
              placeholder={
                bodyKind === "sql"
                  ? "SELECT ..."
                  : "Show me the top 10 slow queries from the last hour"
              }
              className="mt-1 w-full rounded border border-slate-600 bg-slate-800 px-3 py-2 font-mono text-xs text-slate-200 focus:border-blue-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="text-xs text-slate-400">Tier hint</label>
            <select
              value={tierHint}
              onChange={(e) =>
                setTierHint(Number(e.target.value) as 1 | 2 | 3)
              }
              className="mt-1 w-full rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 focus:border-blue-500 focus:outline-none"
            >
              <option value={1}>Tier 1 — read</option>
              <option value={2}>Tier 2 — advise</option>
              <option value={3}>Tier 3 — act (requires APPLY)</option>
            </select>
            <p className="mt-1 text-[10px] text-slate-500">
              The server re-classifies SQL bodies on every run; this hint is just
              for filtering/sorting in the UI.
            </p>
          </div>

          {error && (
            <div className="rounded border border-rose-800 bg-rose-950/30 p-2 text-xs text-rose-200">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-700 px-6 py-3">
          <button
            onClick={onClose}
            className="rounded border border-slate-600 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!valid || submitting}
            className="rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40"
          >
            {submitting ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
