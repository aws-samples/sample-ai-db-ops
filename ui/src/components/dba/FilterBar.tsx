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

// Controls for database / principal / severity / source / time range and a
// DDL-only toggle (R6.3, R6.4). Applied to both the timeline and the graph via
// the lib/dba/filters mirror. Presentational only; the parent owns state.

export interface FilterState {
  databases: string[];
  principals: string[];
  severities: string[];
  sources: string[];
  ddlOnly: boolean;
}

const ALL_SOURCES = ["git", "cloudtrail", "agent", "database"];
const ALL_SEVERITIES = ["low", "medium", "high", "critical"];

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

export default function FilterBar({
  state,
  databases,
  principals,
  onChange,
}: {
  state: FilterState;
  /** Distinct database identifiers discovered in the current event set. */
  databases: string[];
  /** Distinct principals discovered in the current event set. */
  principals: string[];
  onChange: (next: FilterState) => void;
}) {
  const toggle = (key: keyof FilterState, value: string) => {
    const list = state[key] as string[];
    const next = list.includes(value)
      ? list.filter((v) => v !== value)
      : [...list, value];
    onChange({ ...state, [key]: next });
  };

  return (
    <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-900/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-20 text-[11px] uppercase text-slate-500">Source</span>
        {ALL_SOURCES.map((s) => (
          <Chip key={s} label={s} active={state.sources.includes(s)} onClick={() => toggle("sources", s)} />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-20 text-[11px] uppercase text-slate-500">Severity</span>
        {ALL_SEVERITIES.map((s) => (
          <Chip key={s} label={s} active={state.severities.includes(s)} onClick={() => toggle("severities", s)} />
        ))}
      </div>
      {databases.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-20 text-[11px] uppercase text-slate-500">Database</span>
          {databases.map((d) => (
            <Chip key={d} label={d} active={state.databases.includes(d)} onClick={() => toggle("databases", d)} />
          ))}
        </div>
      )}
      {principals.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-20 text-[11px] uppercase text-slate-500">Principal</span>
          {principals.map((p) => (
            <Chip key={p} label={p} active={state.principals.includes(p)} onClick={() => toggle("principals", p)} />
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-20 text-[11px] uppercase text-slate-500">DDL only</span>
        <Chip
          label={state.ddlOnly ? "on" : "off"}
          active={state.ddlOnly}
          onClick={() => onChange({ ...state, ddlOnly: !state.ddlOnly })}
        />
      </div>
    </div>
  );
}
