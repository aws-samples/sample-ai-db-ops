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

// GET /api/dba/node/:node_id?days=1..365
//
// Admin-guarded, GET-only, gated (approved only), audited. Returns
// { node, neighbors } for one-hop expand / re-center. Built from
// query.connected at hops=1 so the read-only invariant is preserved.
// (R6.7, R8.2)

import { NextRequest, NextResponse } from "next/server";
import { withAdminGuard } from "@/lib/auth/admin";
import { runGated, PythonBridgeError } from "@/lib/dba/bridge";

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ node_id: string }> },
) {
  const { node_id } = await ctx.params;
  return withAdminGuard(req, "dba_node", async (userId) => {
    const url = new URL(req.url);
    const days = parseInt(url.searchParams.get("days") ?? "365", 10);

    try {
      const env = await runGated<unknown>({
        userId,
        route: "dba_node",
        focus: node_id,
        args: { node_id, days },
        queryBody: `
from src.admin_ops.kg import store
from src.admin_ops.kg.query import connected, TraversalParams, InvalidQuery
try:
    node = store._get_backend().get_node(a["node_id"])
    if node is None:
        result = {"ok": False, "invalid_parameter": "node_id"}
    else:
        res = connected(TraversalParams(
            focus_node_id=a["node_id"], hops=1, days=a["days"]))
        result = {
            "ok": True,
            "node": node.model_dump(mode="json"),
            "neighbors": res.model_dump(mode="json"),
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
        | { ok: true; node: unknown; neighbors: unknown }
        | { ok: false; invalid_parameter: string };
      if (!data.ok) {
        const status = data.invalid_parameter === "node_id" ? 404 : 400;
        return NextResponse.json(
          { error: `invalid parameter: ${data.invalid_parameter}` },
          { status },
        );
      }
      return NextResponse.json({
        node: data.node,
        neighbors: data.neighbors,
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
