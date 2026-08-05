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

// POST /api/admin/sql/classify  — classify a SQL/DDB body into a Tier.
// Used by the SQL_Editor for the live tier badge.

import { NextRequest, NextResponse } from "next/server";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";
import { withAdminGuard } from "@/lib/auth/admin";

interface Body {
  engine: string;
  body: string;
}

export async function POST(req: NextRequest) {
  // Classification is admin-only for consistency with the SQL runner it feeds:
  // leaving it open would let an unauthorized caller probe how arbitrary
  // statements are categorized.
  return withAdminGuard(req, "admin.sql.classify", async () => classifySql(req));
}

async function classifySql(req: NextRequest) {
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
from src.admin_ops.admin.sql.classifier import classify
c = classify(${JSON.stringify(json.engine)}, ${JSON.stringify(json.body)})
print(json.dumps({"tier": c.tier, "leading_keyword": c.leading_keyword, "reason": c.reason}))
`);
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}
