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

// GET /api/dba/unticketed?days=1..365
//
// Admin-guarded, GET-only, gated (approved only), audited. Returns high/
// critical DDL ChangeEvents with no CAUSED_BY ticket, plus a `complete` flag.
// (R7.4)

import { NextRequest, NextResponse } from "next/server";
import { withAdminGuard } from "@/lib/auth/admin";
import { runGated, PythonBridgeError } from "@/lib/dba/bridge";

export async function GET(req: NextRequest) {
  return withAdminGuard(req, "dba_unticketed", async (userId) => {
    const url = new URL(req.url);
    const days = parseInt(url.searchParams.get("days") ?? "30", 10);

    try {
      const env = await runGated<unknown>({
        userId,
        route: "dba_unticketed",
        args: { days },
        queryBody: `
from src.admin_ops.kg.query import unticketed_changes, InvalidQuery
try:
    res = unticketed_changes(a["days"])
    result = {
        "ok": True,
        "events": [n.model_dump(mode="json") for n in res.events],
        "complete": res.complete,
        "reason": res.reason,
    }
except InvalidQuery as exc:
    result = {"ok": False, "invalid_parameter": exc.parameter}
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
      const data = env.data as
        | { ok: true; events: unknown[]; complete: boolean; reason: string | null }
        | { ok: false; invalid_parameter: string };
      if (!data.ok) {
        return NextResponse.json(
          { error: `invalid parameter: ${data.invalid_parameter}` },
          { status: 400 },
        );
      }
      return NextResponse.json({
        events: data.events,
        complete: data.complete,
        reason: data.reason,
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
