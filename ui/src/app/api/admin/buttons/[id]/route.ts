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

// PATCH  /api/admin/buttons/:id   — patch fields
// DELETE /api/admin/buttons/:id   — delete

import { NextRequest, NextResponse } from "next/server";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";
import { withAdminGuard } from "@/lib/auth/admin";

export async function PATCH(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  // Admin-gated: updating a stored button mutates admin configuration.
  return withAdminGuard(req, "admin.buttons.update", async (uid) =>
    patchButton(req, ctx, uid),
  );
}

async function patchButton(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
  uid: string,
) {
  const { id } = await ctx.params;
  const patch = (await req.json().catch(() => null)) as unknown;
  if (!patch || typeof patch !== "object") {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }
  try {
    const updated = await callPython<unknown>(`
import json
from uuid import UUID
from src.admin_ops.admin.buttons.store import update_button
from src.admin_ops.admin.buttons.schema import CustomButtonPatch
patch = CustomButtonPatch.model_validate(json.loads(${JSON.stringify(JSON.stringify(patch))}))
b = update_button(${JSON.stringify(uid)}, UUID(${JSON.stringify(id)}), patch)
print(json.dumps(b.model_dump(mode="json")))
`);
    return NextResponse.json(updated);
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}

export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  // Admin-gated: deletion is destructive and must not be reachable by an
  // unauthorized caller.
  return withAdminGuard(req, "admin.buttons.delete", async (uid) =>
    deleteButton(ctx, uid),
  );
}

async function deleteButton(
  ctx: { params: Promise<{ id: string }> },
  uid: string,
) {
  const { id } = await ctx.params;
  try {
    await callPython<unknown>(`
import json
from uuid import UUID
from src.admin_ops.admin.buttons.store import delete_button
delete_button(${JSON.stringify(uid)}, UUID(${JSON.stringify(id)}))
print(json.dumps({"deleted": ${JSON.stringify(id)}}))
`);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}
