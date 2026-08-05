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

// GET /api/reports?db=<db_identifier>&page_size=25
// Lists prior Health_Reports for the selected database in reverse
// chronological order (R3.16). Reads from the in-memory archive when
// running locally; in production this is the dbops-report-runs DDB
// table.

import { NextRequest, NextResponse } from "next/server";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const db = url.searchParams.get("db") ?? "";
  const pageSize = url.searchParams.get("page_size") ?? "25";
  if (!db) {
    return NextResponse.json({ error: "db is required" }, { status: 400 });
  }
  try {
    const data = await callPython<unknown>(`
import json
from src.admin_ops.reports.archive import list_runs

runs, _ = list_runs(${JSON.stringify(db)}, page_size=int(${JSON.stringify(pageSize)}))
print(json.dumps({"runs": runs}))
`);
    return NextResponse.json(data);
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}
