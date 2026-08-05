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

// GET /api/admin/templates/[id] — fetch a single template spec.

import { NextRequest, NextResponse } from "next/server";
import { withAdminGuard } from "@/lib/auth/admin";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return withAdminGuard(req, "templates.get", async () => {
    if (!/^[a-z][a-z0-9_]*$/.test(id)) {
      return NextResponse.json({ error: "invalid template id" }, { status: 400 });
    }
    try {
      const spec = await callPython<Record<string, unknown> | { error: string }>(`
from src.admin_ops.registry.loader import registry
registry.load()
spec = registry.get(${JSON.stringify(id)})
if spec is None:
    print(json.dumps({"error": "not_found"}))
else:
    print(json.dumps(spec.model_dump(mode="json")))
`);
      if (spec && typeof spec === "object" && "error" in spec) {
        return NextResponse.json(spec, { status: 404 });
      }
      return NextResponse.json(spec);
    } catch (err) {
      if (err instanceof PythonBridgeError) {
        return NextResponse.json({ error: err.message }, { status: 503 });
      }
      throw err;
    }
  });
}
