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

// GET /api/admin/templates — list every template in the registry.
//
// Bridges to TemplateRegistry.all(). Returns the spec metadata only;
// the body is included so the detail drawer can render it without a
// second round-trip. Guarded by withAdminGuard.

import { NextRequest, NextResponse } from "next/server";
import { withAdminGuard } from "@/lib/auth/admin";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";

interface TemplateListResponse {
  templates: Array<Record<string, unknown>>;
  failures: Array<{ path: string; template_id: string | null; reason: string }>;
}

export async function GET(req: NextRequest) {
  return withAdminGuard(req, "templates.list", async () => {
    try {
      const data = await callPython<TemplateListResponse>(`
from src.admin_ops.registry.loader import registry
registry.load()
specs = [s.model_dump(mode="json") for s in registry.all()]
failures = [
    {"path": f.path, "template_id": f.template_id, "reason": f.reason}
    for f in registry.failures()
]
print(json.dumps({"templates": specs, "failures": failures}))
`);
      return NextResponse.json(data);
    } catch (err) {
      if (err instanceof PythonBridgeError) {
        return NextResponse.json({ error: err.message }, { status: 503 });
      }
      throw err;
    }
  });
}
