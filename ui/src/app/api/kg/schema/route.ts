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

// GET /api/kg/schema
//
// Admin-guarded, GET-only static schema endpoint. Returns the closed node/edge
// type lists in `pending` / `approved`; returns not-available in
// `not_approved`. Emits one audit entry per access; fails closed on a
// gate-unavailable misconfig. (R3.1, R3.2, R4.4, R4.5)

import { NextRequest, NextResponse } from "next/server";
import { withAdminGuard } from "@/lib/auth/admin";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";

interface SchemaResponse {
  available: boolean;
  gating_state: string | null;
  node_types?: string[];
  edge_types?: string[];
  _audit_failed?: boolean;
}

export async function GET(req: NextRequest) {
  return withAdminGuard(req, "kg_schema", async (userId) => {
    try {
      const data = await callPython<SchemaResponse>(`
import json
from src.admin_ops.kg import gate
from src.admin_ops.kg.schema import NODE_TYPES, EDGE_TYPES
from src.admin_ops.kg.audit import emit_access, AuditEmitFailed
from src.admin_ops.kg.gate import GateUnavailable

try:
    emit_access(user_id=${JSON.stringify(userId)}, route="kg_schema")
except AuditEmitFailed:
    print(json.dumps({"_audit_failed": True})); raise SystemExit

try:
    state = gate.gating_state()
except GateUnavailable:
    print(json.dumps({"available": False, "gating_state": None})); raise SystemExit

# Static schema is served in pending + approved; withheld in not_approved.
if state == "not_approved":
    print(json.dumps({"available": False, "gating_state": state})); raise SystemExit

print(json.dumps({
    "available": True,
    "gating_state": state,
    "node_types": sorted(NODE_TYPES),
    "edge_types": sorted(EDGE_TYPES),
}))
`);
      if (data._audit_failed) {
        return NextResponse.json({ error: "audit emit failed" }, { status: 500 });
      }
      return NextResponse.json(data);
    } catch (err) {
      if (err instanceof PythonBridgeError) {
        return NextResponse.json({ error: err.message }, { status: 503 });
      }
      throw err;
    }
  });
}
