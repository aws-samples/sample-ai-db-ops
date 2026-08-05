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

// Internal-only resolver invoked by the admin middleware. Forwards to
// the Python `src/admin_ops/admin/role.is_admin` via a short-lived
// subprocess (mirrors the pattern used by `/api/invoke`).
//
// Refuses to serve unless the caller is an internal Next.js call
// (header `x-internal-call: 1`). This is a defense-in-depth measure;
// the route is also locked down at the network layer in production.

import { NextRequest, NextResponse } from "next/server";
import { exec } from "child_process";
import { promisify } from "util";
import { writeFile, unlink } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";

const execAsync = promisify(exec);
const PYTHON = process.env.PYTHON_BIN ?? "python3";

export async function POST(req: NextRequest) {
  if (req.headers.get("x-internal-call") !== "1") {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }
  const body = (await req.json()) as { user_id?: string };
  const userId = body.user_id ?? "";
  if (!userId || userId.length > 128) {
    return NextResponse.json({ is_admin: false });
  }

  const scriptPath = join(tmpdir(), `dbops_admin_check_${Date.now()}.py`);
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(process.cwd().replace(/\/ui$/, ""))})
from src.admin_ops.admin.role import is_admin, AdminSourceUnreachable, InvalidUserId
try:
    print(json.dumps({"is_admin": bool(is_admin(${JSON.stringify(userId)}))}))
except (AdminSourceUnreachable, Exception) as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(2)
`;
  await writeFile(scriptPath, script);
  try {
    const { stdout } = await execAsync(`${PYTHON} ${scriptPath}`, {
      timeout: 10_000,
    });
    return NextResponse.json(JSON.parse(stdout.trim()));
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 503 },
    );
  } finally {
    await unlink(scriptPath).catch(() => {});
  }
}
