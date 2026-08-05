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

interface CloneModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (config: CloneConfig) => void;
  sourceDb: string;
}

interface TableConfig {
  name: string;
  selected: boolean;
  maskColumns: string[];
  availableColumns: string[];
}

export interface CloneConfig {
  sourceDb: string;
  targetEnv: string;
  tables: { name: string; maskColumns: string[]; maskingType: string }[];
  maskingEnabled: boolean;
  maskingType: string;
}

// Column-name fragments that commonly denote data carrying a regulatory
// obligation. Used to pre-select columns for masking and to surface the notice
// below — a name-based heuristic, not a data classification, so it names what it
// matched rather than asserting what the column contains.
const REGULATED_COLUMN_HINTS = [
  "card_number", "cardnumber", "cvv", "iban", "account_number", "sort_code",
  "ssn", "national_id", "passport", "nino",
  "email", "phone", "mobile", "dob", "birth", "address", "postcode",
  "patient", "mrn", "diagnosis",
  "token", "secret", "password",
];

/** Return the columns of `table` whose names suggest a regulatory obligation. */
function regulatedColumns(columns: string[]): string[] {
  return columns.filter(c =>
    REGULATED_COLUMN_HINTS.some(h => c.toLowerCase().includes(h)),
  );
}

// Illustrative table list for the demo UI — not read from a live schema. The
// column names are deliberately realistic so the masking workflow is meaningful,
// which is also why the compliance notice below exists.
const SAMPLE_TABLES: TableConfig[] = [
  { name: "users", selected: true, maskColumns: [], availableColumns: ["email", "phone", "ssn", "name", "address"] },
  { name: "orders", selected: true, maskColumns: [], availableColumns: ["customer_id", "total", "shipping_address"] },
  { name: "payments", selected: false, maskColumns: [], availableColumns: ["card_number", "cvv", "billing_address", "amount"] },
  { name: "sessions", selected: false, maskColumns: [], availableColumns: ["token", "ip_address", "user_agent"] },
  { name: "audit_log", selected: false, maskColumns: [], availableColumns: ["user_id", "action", "details"] },
];

export default function CloneModal({ isOpen, onClose, onSubmit, sourceDb }: CloneModalProps) {
  const [tables, setTables] = useState<TableConfig[]>(SAMPLE_TABLES);
  const [maskingEnabled, setMaskingEnabled] = useState(true);
  const [maskingType, setMaskingType] = useState("partial");
  const [targetEnv, setTargetEnv] = useState("development");

  if (!isOpen) return null;

  // Columns across the *selected* tables whose names suggest regulated data.
  // Drives the notice below, so it disappears once those tables are deselected.
  const selectedRegulated = tables
    .filter(t => t.selected)
    .flatMap(t => regulatedColumns(t.availableColumns).map(c => `${t.name}.${c}`));

  const toggleTable = (name: string) => {
    setTables(tables.map(t => {
      if (t.name !== name) return t;
      const selected = !t.selected;
      // Selecting a table pre-marks its regulated-looking columns for masking, so
      // the safer configuration is the default and un-masking one is a deliberate
      // act. The operator can still uncheck them — this is a sample, and a column
      // matching the heuristic is not necessarily in scope for any regulation.
      return selected
        ? { ...t, selected, maskColumns: regulatedColumns(t.availableColumns) }
        : { ...t, selected };
    }));
  };

  const toggleColumn = (tableName: string, col: string) => {
    setTables(tables.map(t => {
      if (t.name !== tableName) return t;
      const cols = t.maskColumns.includes(col)
        ? t.maskColumns.filter(c => c !== col)
        : [...t.maskColumns, col];
      return { ...t, maskColumns: cols };
    }));
  };

  const handleSubmit = () => {
    const config: CloneConfig = {
      sourceDb,
      targetEnv,
      tables: tables.filter(t => t.selected).map(t => ({
        name: t.name,
        maskColumns: maskingEnabled ? t.maskColumns : [],
        maskingType,
      })),
      maskingEnabled,
      maskingType,
    };
    onSubmit(config);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-[700px] max-h-[85vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-700 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold">🔄 Replicate Tables to Lower Environment</h2>
            <p className="text-xs text-slate-400 mt-0.5">Source: <span className="text-blue-300">{sourceDb}</span></p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 hover:bg-slate-800 text-slate-400">✕</button>
        </div>

        {/* Compliance notice. Copying production data into a lower environment can
            bring that environment into scope for the obligations that applied to
            the source, which is easy to overlook when the action is a single
            click. Shown only when a selected table has regulated-looking columns,
            and it names them, so it stays informative rather than becoming a
            banner people learn to ignore. */}
        {selectedRegulated.length > 0 && (
          <div className="mx-6 mt-4 rounded-lg border border-amber-600/50 bg-amber-950/40 px-4 py-3 text-xs text-amber-200">
            <p className="font-semibold">Regulated data may be in scope</p>
            <p className="mt-1">
              These selected columns have names suggesting a regulatory obligation:{" "}
              <span className="font-mono text-amber-100">{selectedRegulated.join(", ")}</span>.
            </p>
            <p className="mt-1">
              Replicating payment card data (for example <span className="font-mono">card_number</span>,{" "}
              <span className="font-mono">cvv</span>) can bring the target environment into PCI DSS
              scope. Replicating personal data (for example <span className="font-mono">ssn</span>,{" "}
              <span className="font-mono">email</span>, <span className="font-mono">phone</span>) is
              subject to privacy regulation such as GDPR and CCPA. Under the AWS shared
              responsibility model, meeting those obligations in your account is yours.
            </p>
            <p className="mt-1">
              Masking here is a development convenience, not a compliance control, and it is not
              anonymisation — <span className="font-mono">partial</span> preserves leading and
              trailing characters, and <span className="font-mono">hash</span> is deterministic and
              unsalted, so values stay linkable. These columns are pre-selected for masking; review
              before proceeding. This list is matched on column names, so treat it as a prompt to
              check rather than as a data classification.
            </p>
          </div>
        )}

        {/* Target Environment */}
        <div className="border-b border-slate-700 px-6 py-4">
          <label className="text-sm font-medium text-slate-300">Target Environment</label>
          <select
            value={targetEnv}
            onChange={(e) => setTargetEnv(e.target.value)}
            className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:border-blue-500 focus:outline-none"
          >
            <option value="development">🟢 Development</option>
            <option value="staging">🟡 Staging</option>
            <option value="qa">🔵 QA</option>
          </select>
        </div>

        {/* Data Masking Toggle */}
        <div className="border-b border-slate-700 px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-sm font-medium text-slate-300">🎭 Data Masking</label>
              <p className="text-xs text-slate-500 mt-0.5">Mask sensitive columns during replication</p>
            </div>
            <button
              onClick={() => setMaskingEnabled(!maskingEnabled)}
              className={`relative h-6 w-11 rounded-full transition-colors ${maskingEnabled ? "bg-blue-600" : "bg-slate-600"}`}
            >
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${maskingEnabled ? "translate-x-5" : "translate-x-0.5"}`} />
            </button>
          </div>

          {maskingEnabled && (
            <div className="mt-3 flex gap-2">
              {["partial", "full", "hash"].map((type) => (
                <button
                  key={type}
                  onClick={() => setMaskingType(type)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                    maskingType === type
                      ? "bg-blue-600 text-white"
                      : "bg-slate-800 text-slate-400 border border-slate-600 hover:border-slate-500"
                  }`}
                >
                  {type === "partial" ? "Ab****cd" : type === "full" ? "*****" : "#hash"}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Table Selection */}
        <div className="px-6 py-4">
          <label className="text-sm font-medium text-slate-300">Select Tables</label>
          <div className="mt-3 space-y-3">
            {tables.map((table) => (
              <div key={table.name} className={`rounded-lg border p-3 transition ${table.selected ? "border-blue-600 bg-blue-950/30" : "border-slate-700 bg-slate-800/30"}`}>
                {/* Table row */}
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={table.selected}
                    onChange={() => toggleTable(table.name)}
                    className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-sm font-medium">{table.name}</span>
                </div>

                {/* Column masking (only if table selected and masking enabled) */}
                {table.selected && maskingEnabled && (
                  <div className="mt-2 ml-7 flex flex-wrap gap-1.5">
                    {table.availableColumns.map((col) => (
                      <button
                        key={col}
                        onClick={() => toggleColumn(table.name, col)}
                        className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition ${
                          table.maskColumns.includes(col)
                            ? "bg-purple-600/30 text-purple-300 border border-purple-500"
                            : "bg-slate-700/50 text-slate-400 border border-slate-600 hover:border-purple-500"
                        }`}
                      >
                        {table.maskColumns.includes(col) ? "🎭 " : ""}{col}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-700 px-6 py-4">
          <div className="text-xs text-slate-500">
            {tables.filter(t => t.selected).length} tables selected
            {maskingEnabled && ` • ${tables.reduce((acc, t) => acc + t.maskColumns.length, 0)} columns masked`}
          </div>
          <div className="flex gap-3">
            <button onClick={onClose} className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
              Cancel
            </button>
            <button onClick={handleSubmit} className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-500">
              🚀 Start Clone
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
