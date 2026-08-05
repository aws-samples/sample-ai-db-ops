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

// Shared gating + audit bridge for the DBA View / KG read-only routes.
//
// Every /api/dba/* and /api/kg/* data route is:
//   1. admin-guarded (withAdminGuard, in the route),
//   2. audited exactly once per access (Python emit_access),
//   3. gating-checked fail-closed (Python gate.gating_state()),
//   4. read-only (GET only; query.* never mutates).
//
// This helper centralizes 2-4 so each route only supplies its query body.
// The audit emission and gate check run Python-side (the source of truth),
// matching design.md's bridge example. The returned envelope distinguishes:
//   - audit failure       -> { kind: "audit_failed" }   (route -> HTTP 500)
//   - gate unavailable     -> available:false, gating_state:null (fail closed)
//   - pending/not_approved -> available:false, gating_state:<state>
//   - approved             -> available:true, data:<result>
// PythonBridgeError (process/connectivity failure) -> route maps to HTTP 503.

import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";

export { PythonBridgeError };

export interface GatedEnvelope<T> {
  available: boolean;
  gating_state: string | null;
  data?: T;
  /** Present only when the audit emit failed (R9.5) — route returns 500. */
  _audit_failed?: boolean;
}

export interface RunGatedOptions {
  /** The user_id from withAdminGuard; used for the audit entry. */
  userId: string;
  /** Audit route/query id, e.g. "dba_graph". */
  route: string;
  /** Optional focus node_id recorded on the audit entry. */
  focus?: string | null;
  /** Values made available to the query body as the dict `a`. */
  args?: Record<string, unknown>;
  /**
   * Python lines, run ONLY when gating is `approved`, that must assign a
   * JSON-serializable value to `result`. The parsed `args` are in scope as
   * `a`; helpers `_dt(v)` (ISO/date -> aware datetime or None) are available.
   */
  queryBody: string;
  timeoutMs?: number;
}

/**
 * Run a gated, audited, read-only query body through the Python bridge.
 * Returns the parsed {@link GatedEnvelope}. Throws {@link PythonBridgeError}
 * on a process/connectivity failure so the route can map it to HTTP 503.
 */
export async function runGated<T>(opts: RunGatedOptions): Promise<GatedEnvelope<T>> {
  const args = {
    ...(opts.args ?? {}),
    __user_id: opts.userId,
    __focus: opts.focus ?? null,
  };
  const argsJson = JSON.stringify(JSON.stringify(args));
  const routeJson = JSON.stringify(opts.route);

  const script = `
import json
from datetime import datetime, timezone
from src.admin_ops.kg import gate
from src.admin_ops.kg.audit import emit_access, AuditEmitFailed
from src.admin_ops.kg.gate import GateUnavailable

a = json.loads(${argsJson})


def _dt(v):
    if not v:
        return None
    s = v if "T" in v else v + "T00:00:00+00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


# 1. Audit first (R9.2). An audit failure fails the request with no data (R9.5).
try:
    emit_access(user_id=a["__user_id"], route=${routeJson}, focus=a.get("__focus"))
except AuditEmitFailed:
    print(json.dumps({"available": False, "gating_state": None, "_audit_failed": True}))
    raise SystemExit

# 2. Gating, fail closed (R4.4-R4.6, R10.4).
try:
    state = gate.gating_state()
except GateUnavailable:
    print(json.dumps({"available": False, "gating_state": None}))
    raise SystemExit

if state != "approved":
    print(json.dumps({"available": False, "gating_state": state}))
    raise SystemExit

# 3. Approved: run the read-only query body (must assign the variable result).
${opts.queryBody}

# stdout is the transport back to the Node caller, not a log sink: callPython
# parses this line and discards it. Only stderr is logged, and that is redacted
# (see ui/src/lib/redact.ts). The query result therefore reaches the admin-gated
# HTTP response and nothing else -- it is never written to a log destination.
print(json.dumps({"available": True, "gating_state": state, "data": result}))
`;

  return callPython<GatedEnvelope<T>>(script, { timeoutMs: opts.timeoutMs });
}
