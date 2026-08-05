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

// GET /api/kg/health
//
// Admin-guarded, GET-only health endpoint for the DBA knowledge graph. Always
// responds; `status` reflects the gating state (ok | pending | not_available).
// Emits one audit entry per access. A gate-unavailable (misconfig) fails
// closed to not_available. (R1.7, R4.4, R4.5)

import { NextRequest, NextResponse } from "next/server";
import { withAdminGuard } from "@/lib/auth/admin";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";

export async function GET(req: NextRequest) {
  return withAdminGuard(req, "kg_health", async (userId) => {
    try {
      const data = await callPython<{ status: string; gating_state: string | null }>(`
import json
from src.admin_ops.kg import gate
from src.admin_ops.kg.audit import emit_access, AuditEmitFailed
from src.admin_ops.kg.gate import GateUnavailable

try:
    emit_access(user_id=${JSON.stringify(userId)}, route="kg_health")
except AuditEmitFailed:
    print(json.dumps({"_audit_failed": True})); raise SystemExit

try:
    state = gate.gating_state()
except GateUnavailable:
    print(json.dumps({"status": "not_available", "gating_state": None})); raise SystemExit

status = {"approved": "ok", "pending": "pending", "not_approved": "not_available"}[state]
print(json.dumps({"status": status, "gating_state": state}))
`);
      if ((data as { _audit_failed?: boolean })._audit_failed) {
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
