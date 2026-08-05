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

// GET /api/admin/changes
//   ?source=git,agent&engine=postgresql&severity=high,critical
//   &from=2026-01-01&to=2026-12-31&page=1&page_size=50
//
// Read-only Change Feed query (R4.10, R4.11, R4.16). Returns
// { events, page, total_pages }.
//
// SECURITY: design.md originally classified this as Tier 1 (no admin role
// required). It is now admin-gated: the change feed exposes operational
// governance history — which principal changed which database object, when,
// and under which ticket — and every other governance surface (/api/dba/*,
// /api/kg/*) is already gated. Leaving this one open was an inconsistency
// with the documented fail-closed posture, so the guard is applied here too.

import { NextRequest, NextResponse } from "next/server";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";
import { withAdminGuard } from "@/lib/auth/admin";

function csv(v: string | null): string[] | null {
  if (!v) return null;
  const parts = v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return parts.length ? parts : null;
}

export async function GET(req: NextRequest) {
  return withAdminGuard(req, "admin.changes.list", async () => listChanges(req));
}

async function listChanges(req: NextRequest) {
  const url = new URL(req.url);
  const sources = csv(url.searchParams.get("source"));
  const engines = csv(url.searchParams.get("engine"));
  const severities = csv(url.searchParams.get("severity"));
  const timeFrom = url.searchParams.get("from");
  const timeTo = url.searchParams.get("to");
  const page = parseInt(url.searchParams.get("page") ?? "1", 10) || 1;
  const pageSize = Math.min(
    parseInt(url.searchParams.get("page_size") ?? "50", 10) || 50,
    200,
  );

  const filterArg = JSON.stringify({
    sources,
    engines,
    severities,
    time_from: timeFrom,
    time_to: timeTo,
  });

  try {
    const data = await callPython<unknown>(`
import json
from datetime import datetime, timezone
from src.admin_ops.changefeed.store import query, ChangeFeedFilter

raw = json.loads(${JSON.stringify(filterArg)})

def _dt(v):
    if not v:
        return None
    s = v if "T" in v else v + "T00:00:00+00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d

f = ChangeFeedFilter(
    sources=raw.get("sources"),
    engines=raw.get("engines"),
    severities=raw.get("severities"),
    time_from=_dt(raw.get("time_from")),
    time_to=_dt(raw.get("time_to")),
)
res = query(f, page=${page}, page_size=${pageSize})
print(json.dumps({
    "events": [e.model_dump(mode="json") for e in res["events"]],
    "page": res["page"],
    "total_pages": res["total_pages"],
}))
`);
    return NextResponse.json(data);
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}
