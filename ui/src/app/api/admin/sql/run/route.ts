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

// POST /api/admin/sql/run  — classify then execute or forward.
// Body: {engine, body, params?, apply_token?}

import { NextRequest, NextResponse } from "next/server";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";
import { withAdminGuard } from "@/lib/auth/admin";

interface Body {
  engine?: string;
  body?: string;
  params?: Record<string, unknown>;
  apply_token?: string;
}

export async function POST(req: NextRequest) {
  // Executing SQL is a privileged operation, so authorization is resolved
  // against the admin source of truth rather than inferred from a
  // client-supplied user id. The guard fails closed: a missing/invalid id is
  // 401, an unreachable admin source is 503, and a non-admin is 403.
  return withAdminGuard(req, "admin.sql.run", async (uid) => runSql(req, uid));
}

async function runSql(req: NextRequest, uid: string) {
  const json = (await req.json().catch(() => null)) as Body | null;
  if (!json || typeof json.engine !== "string" || typeof json.body !== "string") {
    return NextResponse.json(
      { error: "engine and body are required" },
      { status: 400 },
    );
  }

  try {
    const result = await callPython<unknown>(`
import json
from src.admin_ops.admin.sql.runner import run, TierThreeRequiresApply, AgentInvocationFailed
try:
    result = run(
        engine=${JSON.stringify(json.engine)},
        body=${JSON.stringify(json.body)},
        user_id=${JSON.stringify(uid)},
        params=${JSON.stringify(json.params ?? null)},
        apply_token=${JSON.stringify(json.apply_token ?? null)},
    )
except TierThreeRequiresApply as e:
    print(json.dumps({"error": "tier3_requires_apply", "detail": str(e)}))
    sys.exit(0)
except AgentInvocationFailed as e:
    print(json.dumps({"error": "agent_failed", "detail": str(e)}))
    sys.exit(0)

print(json.dumps({
    "tier": result.classification.tier,
    "leading_keyword": result.classification.leading_keyword,
    "reason": result.classification.reason,
    "rows": result.rows,
    "rowcount": result.rowcount,
    "forwarded_to_agent": result.forwarded_to_agent,
}))
`);

    if (
      typeof result === "object" &&
      result !== null &&
      "error" in result &&
      (result as { error: string }).error === "tier3_requires_apply"
    ) {
      return NextResponse.json(result, { status: 412 });
    }
    if (
      typeof result === "object" &&
      result !== null &&
      "error" in result &&
      (result as { error: string }).error === "agent_failed"
    ) {
      return NextResponse.json(result, { status: 502 });
    }
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}
