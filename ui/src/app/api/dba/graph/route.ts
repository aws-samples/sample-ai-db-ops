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

// GET /api/dba/graph?focus=<node_id>&hops=1..3&days=1..365
//
// Admin-guarded, GET-only, gated (approved only), audited. Bounded traversal
// from a focus node via Python query.connected. Invalid params return 400
// naming the offending parameter; a gate/process failure maps to 503.
// (R5.1, R5.2, R5.3, R5.7)

import { NextRequest, NextResponse } from "next/server";
import { withAdminGuard } from "@/lib/auth/admin";
import { runGated, PythonBridgeError } from "@/lib/dba/bridge";

export async function GET(req: NextRequest) {
  return withAdminGuard(req, "dba_graph", async (userId) => {
    const url = new URL(req.url);
    const focus = url.searchParams.get("focus") ?? "";
    const hops = parseInt(url.searchParams.get("hops") ?? "1", 10);
    const days = parseInt(url.searchParams.get("days") ?? "30", 10);

    try {
      const env = await runGated<unknown>({
        userId,
        route: "dba_graph",
        focus,
        args: { focus, hops, days },
        queryBody: `
from src.admin_ops.kg.query import connected, TraversalParams, InvalidQuery
try:
    res = connected(TraversalParams(
        focus_node_id=a["focus"], hops=a["hops"], days=a["days"]))
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
