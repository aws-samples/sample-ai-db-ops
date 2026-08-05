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

// GET  /api/admin/buttons          — list this user's buttons (with optional team)
// POST /api/admin/buttons          — create a new button

import { NextRequest, NextResponse } from "next/server";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";
import { withAdminGuard } from "@/lib/auth/admin";

export async function GET(req: NextRequest) {
  // Admin-gated: the identity is resolved against the admin source of truth
  // rather than trusted from a client-supplied header/cookie.
  return withAdminGuard(req, "admin.buttons.list", async (uid) => listButtons(req, uid));
}

async function listButtons(req: NextRequest, uid: string) {
  const url = new URL(req.url);
  const engine = url.searchParams.get("engine") ?? "";
  const teamId = url.searchParams.get("team_id") ?? "";
  // Convert JS null to Python None for safe interpolation.
  const teamArg = teamId ? JSON.stringify(teamId) : "None";
  const engineArg = engine ? JSON.stringify(engine) : "None";
  try {
    const buttons = await callPython<unknown>(`
from src.admin_ops.admin.buttons.store import list_buttons
buttons = list_buttons(${JSON.stringify(uid)}, ${teamArg}, ${engineArg})
print(json.dumps([b.model_dump(mode="json") for b in buttons]))
`);
    return NextResponse.json({ buttons });
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}

export async function POST(req: NextRequest) {
  return withAdminGuard(req, "admin.buttons.create", async (uid) => createButton(req, uid));
}

async function createButton(req: NextRequest, uid: string) {
  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }
  try {
    const created = await callPython<unknown>(`
import json
from src.admin_ops.admin.buttons.store import create_button
from src.admin_ops.admin.buttons.schema import CustomButtonCreate
payload = json.loads(${JSON.stringify(JSON.stringify(payload))})
try:
    create = CustomButtonCreate.model_validate(payload)
except Exception as e:
    print(json.dumps({"error": str(e), "code": "validation"}))
    sys.exit(0)
button = create_button(${JSON.stringify(uid)}, create)
print(json.dumps(button.model_dump(mode="json")))
`);
    if (
      typeof created === "object" &&
      created !== null &&
      "code" in created &&
      (created as { code: string }).code === "validation"
    ) {
      return NextResponse.json(created, { status: 400 });
    }
    return NextResponse.json(created, { status: 201 });
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}
