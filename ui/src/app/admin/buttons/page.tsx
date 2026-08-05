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
import CustomButtonsGroup from "@/components/admin/CustomButtonsGroup";
import type { Engine } from "@/components/admin/SqlEditorDrawer";

const ENGINES: Array<{ value: Engine; label: string; icon: string }> = [
  { value: "postgresql", label: "PostgreSQL", icon: "🐘" },
  { value: "mysql", label: "MySQL", icon: "🐬" },
  { value: "oracle", label: "Oracle", icon: "🦅" },
  { value: "dynamodb", label: "DynamoDB", icon: "⚡" },
];

export default function ButtonsPage() {
  const [engine, setEngine] = useState<Engine>("postgresql");

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-semibold">Custom Buttons</h1>
        <p className="mt-1 text-xs text-slate-400">
          Per-user buttons that show up in the fleet panel for the selected
          engine. Each button is bound to a saved SQL statement (Tier 1 / 2)
          or a natural-language prompt that gets forwarded to the agent.
        </p>
      </header>

      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">Engine:</span>
        <div className="inline-flex rounded border border-slate-800 overflow-hidden">
          {ENGINES.map((e) => (
            <button
              key={e.value}
              onClick={() => setEngine(e.value)}
              className={`px-3 py-1 text-xs ${
                engine === e.value
                  ? "bg-slate-800 text-slate-100"
                  : "text-slate-400 hover:bg-slate-900"
              }`}
            >
              <span className="mr-1">{e.icon}</span>
              {e.label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
        <CustomButtonsGroup engine={engine} />
      </div>

      <p className="text-[11px] text-slate-500">
        Tip: Tier 3 statements (DELETE/DROP/UPDATE without WHERE, etc.) require
        you to type <code className="font-mono">APPLY</code> in the SQL editor
        before they run. The agent also gates them: a Tier 3 tool call halts for
        explicit approval before it executes.
      </p>
    </div>
  );
}
