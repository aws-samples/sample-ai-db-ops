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

interface Card {
  href: string;
  title: string;
  blurb: string;
  icon: string;
}

const CARDS: Card[] = [
  {
    href: "/admin/templates",
    title: "Templates",
    blurb:
      "Versioned tool templates the agents resolve at runtime. Browse, inspect, and edit. Changes generate a Change_Event.",
    icon: "📋",
  },
  {
    href: "/admin/buttons",
    title: "Custom Buttons",
    blurb:
      "Per-user buttons that show up in the fleet panel. Bound to a saved SQL or natural-language prompt.",
    icon: "🧩",
  },
  {
    href: "/admin/changes",
    title: "Change Feed",
    blurb:
      "Security audit trail: every change that alters a SQL query or DB infrastructure, from Git, CloudTrail, and agent Tier-3 actions. Filterable, read-only.",
    icon: "🔐",
  },
  {
    href: "/reports",
    title: "Health Reports",
    blurb:
      "Generate weekly or bi-weekly health reports. Tier-1-only. Markdown, PDF, and CSV exports.",
    icon: "📈",
  },
];

export default function AdminIndex() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-100">
          Admin Operations Console
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Manage the templates, custom buttons, and health reports that drive
          the fleet view. Access is gated by the{" "}
          <code className="font-mono text-slate-300">dbops-admins</code>{" "}
          DynamoDB table.
        </p>
      </header>

      <section className="grid gap-4 md:grid-cols-3">
        {CARDS.map((c) => (
          <Link
            key={c.href}
            href={c.href}
            className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 hover:border-slate-600 hover:bg-slate-900 transition"
          >
            <div className="text-3xl">{c.icon}</div>
            <h2 className="mt-2 text-base font-semibold text-slate-100">
              {c.title}
            </h2>
            <p className="mt-1 text-xs text-slate-400">{c.blurb}</p>
          </Link>
        ))}
      </section>

      <footer className="text-[11px] text-slate-500">
        Audit trail is captured for every privileged action. See{" "}
        <code className="font-mono">src/admin_ops/admin/role.py</code>.
      </footer>
    </div>
  );
}
