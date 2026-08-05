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

export const metadata = {
  title: "DBOps Admin Console",
};

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/60 px-6 py-3">
        <nav className="flex items-center gap-6 text-sm">
          <Link
            href="/admin"
            className="text-slate-100 font-semibold tracking-wide"
          >
            🛠️ Admin Console
          </Link>
          <Link
            href="/admin/templates"
            className="text-slate-400 hover:text-slate-100"
          >
            Templates
          </Link>
          <Link
            href="/admin/buttons"
            className="text-slate-400 hover:text-slate-100"
          >
            Custom Buttons
          </Link>
          <Link
            href="/admin/changes"
            className="text-slate-400 hover:text-slate-100"
          >
            Change Feed
          </Link>
          <Link
            href="/reports"
            className="text-slate-400 hover:text-slate-100"
          >
            Reports
          </Link>
          <span className="ml-auto text-slate-500 text-xs">
            <Link href="/" className="hover:text-slate-300">
              ← Back to fleet
            </Link>
          </span>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
    </div>
  );
}
