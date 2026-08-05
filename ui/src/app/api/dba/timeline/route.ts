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

// GET /api/dba/timeline
//   ?database=a,b&principal=x&severity=high,critical&source=database
//   &from=2026-01-01&to=2026-12-31&ddl_only=1&page=1&page_size=50
//
// Admin-guarded, GET-only, gated (approved only), audited. Filtered,
// reverse-chronological page of ChangeEvents via the kg filter algebra over
// the change-feed store. (R6.2, R6.3, R6.4)

import { NextRequest, NextResponse } from "next/server";
import { withAdminGuard } from "@/lib/auth/admin";
import { runGated, PythonBridgeError } from "@/lib/dba/bridge";

function csv(v: string | null): string[] | null {
  if (!v) return null;
  const parts = v.split(",").map((s) => s.trim()).filter(Boolean);
  return parts.length ? parts : null;
}

export async function GET(req: NextRequest) {
  return withAdminGuard(req, "dba_timeline", async (userId) => {
    const url = new URL(req.url);
    const page = parseInt(url.searchParams.get("page") ?? "1", 10) || 1;
    const pageSize = Math.min(
      parseInt(url.searchParams.get("page_size") ?? "50", 10) || 50,
      50,
    );

    try {
      const env = await runGated<unknown>({
        userId,
        route: "dba_timeline",
        args: {
          databases: csv(url.searchParams.get("database")),
          principals: csv(url.searchParams.get("principal")),
          severities: csv(url.searchParams.get("severity")),
          sources: csv(url.searchParams.get("source")),
          time_from: url.searchParams.get("from"),
          time_to: url.searchParams.get("to"),
          ddl_only: url.searchParams.get("ddl_only") === "1",
          page,
          page_size: pageSize,
        },
        queryBody: `
from src.admin_ops.changefeed.store import _get_backend, dedupe
from src.admin_ops.kg.filters import EventFilter, apply, order_timeline

events = dedupe(_get_backend().all_events())
f = EventFilter(
    databases=a.get("databases"),
    principals=a.get("principals"),
    severities=a.get("severities"),
    sources=a.get("sources"),
    time_from=_dt(a.get("time_from")),
    time_to=_dt(a.get("time_to")),
    ddl_only=bool(a.get("ddl_only")),
)
page = order_timeline(apply(f, events), page=a["page"], page_size=a["page_size"])
result = {
    "events": [e.model_dump(mode="json") for e in page["events"]],
    "page": page["page"],
    "total_pages": page["total_pages"],
}
`,
      });

      if (env._audit_failed) {
        return NextResponse.json({ error: "audit emit failed" }, { status: 500 });
      }
      if (!env.available) {
        return NextResponse.json(
          { available: false, gating_state: env.gating_state },
          { status: 200 },
        );
      }
      return NextResponse.json({
        ...(env.data as object),
        gating_state: env.gating_state,
      });
    } catch (err) {
      if (err instanceof PythonBridgeError) {
        return NextResponse.json({ error: err.message }, { status: 503 });
      }
      throw err;
    }
  });
}
