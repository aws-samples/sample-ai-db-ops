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

// GET /api/dba/database/:node_id/ddl?days=1..365
//
// Admin-guarded, GET-only, gated (approved only), audited. Returns the
// database DDL activity GraphResult via query.database_ddl_activity. (R5.5)

import { NextRequest, NextResponse } from "next/server";
import { withAdminGuard } from "@/lib/auth/admin";
import { runGated, PythonBridgeError } from "@/lib/dba/bridge";

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ node_id: string }> },
) {
  const { node_id } = await ctx.params;
  return withAdminGuard(req, "dba_database_ddl", async (userId) => {
    const url = new URL(req.url);
    const days = parseInt(url.searchParams.get("days") ?? "30", 10);

    try {
      const env = await runGated<unknown>({
        userId,
        route: "dba_database_ddl",
        focus: node_id,
        args: { node_id, days },
        queryBody: `
from src.admin_ops.kg.query import database_ddl_activity, InvalidQuery
try:
    res = database_ddl_activity(a["node_id"], a["days"])
    result = {"ok": True, "graph": res.model_dump(mode="json")}
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
        | { ok: true; graph: Record<string, unknown> }
        | { ok: false; invalid_parameter: string };
      if (!data.ok) {
        return NextResponse.json(
          { error: `invalid parameter: ${data.invalid_parameter}` },
          { status: 400 },
        );
      }
      return NextResponse.json({ ...data.graph, gating_state: env.gating_state });
    } catch (err) {
      if (err instanceof PythonBridgeError) {
        return NextResponse.json({ error: err.message }, { status: 503 });
      }
      throw err;
    }
  });
}
