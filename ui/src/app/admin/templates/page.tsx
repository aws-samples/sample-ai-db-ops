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

import { useEffect, useState } from "react";
import { withUserHeader } from "@/lib/auth/client";

interface TemplateParameter {
  name: string;
  type: string;
  default?: unknown;
  min?: number | null;
  max?: number | null;
  allowed?: string[] | null;
}

interface TemplateSpec {
  template_id: string;
  engine: "postgresql" | "mysql" | "oracle" | "dynamodb";
  tool_function_name: string;
  tier: 1 | 2 | 3;
  description: string;
  owner: string;
  parameters: TemplateParameter[];
  body: string;
  version: number;
  updated_at: string;
  updated_by: string;
}

interface ListResponse {
  templates: TemplateSpec[];
  failures: Array<{ path: string; template_id: string | null; reason: string }>;
}

const TIER_BADGE: Record<number, { label: string; cls: string }> = {
  1: { label: "Tier 1", cls: "bg-emerald-900/40 text-emerald-300 border-emerald-800" },
  2: { label: "Tier 2", cls: "bg-amber-900/40 text-amber-300 border-amber-800" },
  3: { label: "Tier 3", cls: "bg-rose-900/40 text-rose-300 border-rose-800" },
};

const ENGINE_ICON: Record<string, string> = {
  postgresql: "🐘",
  mysql: "🐬",
  oracle: "🦅",
  dynamodb: "⚡",
};

export default function TemplatesPage() {
  const [data, setData] = useState<ListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<TemplateSpec | null>(null);

  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const res = await fetch("/api/admin/templates", {
          headers: withUserHeader(),
          credentials: "include",
        });
        const body = await res.json();
        if (cancel) return;
        if (!res.ok) {
          setError(body?.error || `request failed (${res.status})`);
          return;
        }
        setData(body as ListResponse);
      } catch (err) {
        if (!cancel) setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-semibold">Templates</h1>
        <p className="mt-1 text-xs text-slate-400">
          Templates the agents resolve at runtime. Files live under{" "}
          <code className="font-mono text-slate-300">
            src/admin_ops/registry/templates/&lt;engine&gt;/
          </code>
          .
        </p>
      </header>

      {error && (
        <div className="rounded border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-200">
          <strong>Error:</strong> {error}
        </div>
      )}

      {data?.failures && data.failures.length > 0 && (
        <div className="rounded border border-amber-800 bg-amber-950/30 p-3 text-xs text-amber-200">
          <strong>Load failures ({data.failures.length}):</strong>
          <ul className="mt-1 list-disc list-inside">
            {data.failures.map((f) => (
              <li key={f.path}>
                <span className="font-mono">{f.template_id ?? f.path}</span>: {f.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!data && !error && <p className="text-sm text-slate-500">Loading…</p>}

      {data && data.templates.length === 0 && !error && (
        <p className="text-sm text-slate-500">
          No templates loaded yet. Add YAML files under{" "}
          <code className="font-mono">src/admin_ops/registry/templates/</code>.
        </p>
      )}

      {data && data.templates.length > 0 && (
        <table className="w-full border border-slate-800 text-sm">
          <thead className="bg-slate-900/60 text-[11px] uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left">Template</th>
              <th className="px-3 py-2 text-left">Engine</th>
              <th className="px-3 py-2 text-left">Tier</th>
              <th className="px-3 py-2 text-left">Tool</th>
              <th className="px-3 py-2 text-left">Owner</th>
              <th className="px-3 py-2 text-left">Updated</th>
            </tr>
          </thead>
          <tbody>
            {data.templates.map((t) => (
              <tr
                key={t.template_id}
                className="border-t border-slate-800 hover:bg-slate-900/40 cursor-pointer"
                onClick={() => setActive(t)}
              >
                <td className="px-3 py-2">
                  <div className="font-mono text-slate-100">{t.template_id}</div>
                  <div className="text-[11px] text-slate-500">{t.description}</div>
                </td>
                <td className="px-3 py-2">
                  <span className="text-base">{ENGINE_ICON[t.engine] ?? "▢"}</span>{" "}
                  <span className="text-slate-300">{t.engine}</span>
                </td>
                <td className="px-3 py-2">
                  <span
                    className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${TIER_BADGE[t.tier]?.cls ?? ""}`}
                  >
                    {TIER_BADGE[t.tier]?.label ?? t.tier}
                  </span>
                </td>
                <td className="px-3 py-2 font-mono text-slate-300">
                  {t.tool_function_name}
                </td>
                <td className="px-3 py-2 text-slate-400">{t.owner}</td>
                <td className="px-3 py-2 text-slate-400">
                  v{t.version} · {new Date(t.updated_at).toISOString().slice(0, 10)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {active && (
        <TemplateDetailPanel spec={active} onClose={() => setActive(null)} />
      )}
    </div>
  );
}

function TemplateDetailPanel({
  spec,
  onClose,
}: {
  spec: TemplateSpec;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-30 flex justify-end bg-black/60"
      onClick={onClose}
    >
      <aside
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-[640px] max-w-full flex-col bg-slate-950 border-l border-slate-800 shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div>
            <h2 className="font-mono text-sm text-slate-100">
              {spec.template_id}
            </h2>
            <p className="text-[11px] text-slate-500">
              {spec.engine} · {spec.tool_function_name} · v{spec.version}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-slate-800 px-3 py-1 text-xs text-slate-300 hover:bg-slate-900"
          >
            Close
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {spec.description && (
            <p className="text-sm text-slate-300">{spec.description}</p>
          )}

          <section>
            <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
              Parameters
            </h3>
            {spec.parameters.length === 0 ? (
              <p className="text-xs text-slate-500">No parameters.</p>
            ) : (
              <ul className="space-y-1 text-xs">
                {spec.parameters.map((p) => (
                  <li key={p.name} className="font-mono text-slate-300">
                    <span className="text-slate-100">{p.name}</span>:{" "}
                    <span className="text-slate-400">{p.type}</span>
                    {p.default !== undefined && p.default !== null && (
                      <span className="text-slate-500">
                        {" "}
                        (default: {String(p.default)})
                      </span>
                    )}
                    {p.allowed && (
                      <span className="text-slate-500">
                        {" "}
                        ∈ [{p.allowed.join(", ")}]
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
              Body
            </h3>
            <pre className="overflow-auto rounded border border-slate-800 bg-slate-900/60 px-3 py-2 text-[11px] font-mono text-slate-300 whitespace-pre">
              {spec.body}
            </pre>
          </section>

          <section className="text-[11px] text-slate-500">
            Owned by <span className="text-slate-300">{spec.owner}</span>. Last
            updated by{" "}
            <span className="text-slate-300">{spec.updated_by}</span> at{" "}
            <span className="text-slate-300">{spec.updated_at}</span>.
          </section>
        </div>
      </aside>
    </div>
  );
}
