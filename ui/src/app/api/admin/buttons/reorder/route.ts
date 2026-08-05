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

// POST /api/admin/buttons/reorder
// Body: [{button_id, position}, ...]

import { NextRequest, NextResponse } from "next/server";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";
import { withAdminGuard } from "@/lib/auth/admin";

export async function POST(req: NextRequest) {
  // Admin-gated: reordering mutates stored admin configuration.
  return withAdminGuard(req, "admin.buttons.reorder", async (uid) =>
    reorder(req, uid),
  );
}

async function reorder(req: NextRequest, uid: string) {
  const updates = (await req.json().catch(() => null)) as unknown;
  if (!Array.isArray(updates)) {
    return NextResponse.json({ error: "expected array body" }, { status: 400 });
  }
  try {
    await callPython<unknown>(`
import json
from src.admin_ops.admin.buttons.store import reorder_buttons
from src.admin_ops.admin.buttons.schema import ReorderEntry
items = [ReorderEntry.model_validate(u) for u in json.loads(${JSON.stringify(JSON.stringify(updates))})]
reorder_buttons(${JSON.stringify(uid)}, items)
print(json.dumps({"updated": len(items)}))
`);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}
