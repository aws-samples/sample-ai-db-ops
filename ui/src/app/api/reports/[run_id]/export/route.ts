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

// GET /api/reports/:run_id/export?format=pdf|csv
//
// Re-renders the artifact from the canonical Markdown source. The
// archive holds report.md as the source of truth (R3.5); CSV and PDF
// are derived on demand to keep storage cheap and to satisfy P7
// determinism. R3.6, R3.7.

import { NextRequest, NextResponse } from "next/server";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";
import { withIdentifiedUser } from "@/lib/auth/user";

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ run_id: string }> },
) {
  // Returns report content, so it must not be anonymous. Not admin-gated:
  // reading fleet health reports is an ordinary application-user action.
  return withIdentifiedUser(req, "reports.export", () => exportReport(req, ctx));
}

async function exportReport(
  req: NextRequest,
  ctx: { params: Promise<{ run_id: string }> },
) {
  const url = new URL(req.url);
  const format = url.searchParams.get("format") ?? "pdf";
  const dbId = url.searchParams.get("db") ?? "";
  if (!dbId) {
    return NextResponse.json({ error: "db is required" }, { status: 400 });
  }
  const { run_id } = await ctx.params;
  if (format !== "pdf" && format !== "csv") {
    return NextResponse.json(
      { error: "format must be pdf or csv" },
      { status: 400 },
    );
  }

  try {
    const data = await callPython<{ payload: string; content_type: string; filename: string }>(`
import json, base64
from src.admin_ops.reports.archive import _get_backend, list_runs
from src.admin_ops.reports.exporters.csv import export_csvs
from src.admin_ops.reports.exporters.pdf import export_pdf

backend = _get_backend()
runs, _ = list_runs(${JSON.stringify(dbId)})
target = next((r for r in runs if r["report_run_id"] == ${JSON.stringify(run_id)}), None)
if target is None:
    print(json.dumps({"error": "run_not_found"}))
    sys.exit(0)

prefix = target["s3_prefix"]
md_key = prefix + "report.md"
md_bytes, _ = backend.objects.get(md_key, (b"# Missing report\\n", "text/plain")) if hasattr(backend, "objects") else (b"# Missing report\\n", "text/plain")
md = md_bytes.decode("utf-8") if isinstance(md_bytes, bytes) else str(md_bytes)

format_ = ${JSON.stringify(format)}
if format_ == "csv":
    csvs = export_csvs(md)
    if not csvs:
        print(json.dumps({"error": "no_csv_sections"}))
        sys.exit(0)
    body = "\\n\\n".join(f"# {name}\\n{content}" for name, content in sorted(csvs.items()))
    payload = body.encode("utf-8")
    content_type = "text/csv"
    filename = "report.csv"
else:
    payload = export_pdf(md)
    content_type = "application/pdf" if payload[:4] == b"%PDF" else "text/html"
    filename = "report.pdf" if payload[:4] == b"%PDF" else "report.html"

print(json.dumps({
    "payload": base64.b64encode(payload).decode("ascii"),
    "content_type": content_type,
    "filename": filename,
}))
`);
    if ("error" in data) {
      return NextResponse.json(data, { status: 404 });
    }
    const buffer = Buffer.from(data.payload, "base64");
    return new NextResponse(buffer, {
      status: 200,
      headers: {
        "content-type": data.content_type,
        "content-disposition": `attachment; filename="${data.filename}"`,
      },
    });
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}
