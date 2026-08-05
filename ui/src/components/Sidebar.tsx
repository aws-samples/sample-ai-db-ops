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

interface SidebarProps {
  selectedAgent: string;
  onSelectAgent: (agent: string) => void;
}

const agents = [
  { id: "postgresql", name: "PostgreSQL", icon: "🐘", color: "bg-blue-600" },
  { id: "mysql", name: "MySQL", icon: "🐬", color: "bg-orange-600" },
  { id: "oracle", name: "Oracle", icon: "🦅", color: "bg-red-600" },
  { id: "dynamodb", name: "DynamoDB", icon: "⚡", color: "bg-yellow-600" },
];

export default function Sidebar({ selectedAgent, onSelectAgent }: SidebarProps) {
  return (
    <aside className="flex w-16 flex-col items-center gap-2 border-r border-slate-700 bg-slate-950 py-4">
      {/* Logo */}
      <div className="mb-4 text-2xl">🎮</div>

      {/* Agent Selector */}
      {agents.map((agent) => (
        <button
          key={agent.id}
          onClick={() => onSelectAgent(agent.id)}
          className={`flex h-12 w-12 items-center justify-center rounded-xl text-xl transition-all ${
            selectedAgent === agent.id
              ? `${agent.color} shadow-lg scale-110`
              : "bg-slate-800 hover:bg-slate-700"
          }`}
          title={agent.name}
        >
          {agent.icon}
        </button>
      ))}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Settings */}
      <button className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-800 text-lg hover:bg-slate-700">
        ⚙️
      </button>
    </aside>
  );
}
