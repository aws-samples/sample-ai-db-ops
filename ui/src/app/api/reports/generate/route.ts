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

// POST /api/reports/generate
// Body: { db_identifier, engine?, cadence? }
//
// Fetches the Tier-1 bundle through the agent path and renders the
// Markdown body, persists artifacts to the in-memory archive (or S3
// when configured), returns the rendered Markdown for the UI viewer.
// R3.4 — Tier 1 only. R3.12 — 60s budget.

import { NextRequest, NextResponse } from "next/server";
import { callPython, PythonBridgeError } from "@/lib/admin/python_bridge";

interface Body {
  db_identifier?: string;
  engine?: string;
  cadence?: "weekly" | "bi-weekly" | "manual";
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as Body | null;
  if (!body?.db_identifier) {
    return NextResponse.json(
      { error: "db_identifier is required" },
      { status: 400 },
    );
  }
  const engine = body.engine ?? "postgresql";
  const cadence = body.cadence ?? "manual";

  // We forward to the existing Bedrock invoker by name. The Python
  // generator side expects a callable that returns a Mapping; here we
  // wire it inline via a closure over /api/invoke. For the demo path we
  // keep it simple — the fetcher's stub-friendly invoker pattern is
  // covered by tests/admin_ops/reports/test_fetcher.py.
  try {
    const data = await callPython<unknown>(
      `
import json
from datetime import datetime, timezone
from src.admin_ops.reports.generator import render_report, make_run_id
from src.admin_ops.reports import fetcher
from src.admin_ops.reports import archive
from src.admin_ops.reports.agent_invoker import build_invoker

# Wire the live Bedrock invoker. If agent ARNs are unset or a call
# fails, build_invoker's callable returns {} per tool, so the affected
# section degrades to a "no findings" placeholder (R3.18) instead of
# aborting the run.
fetcher.set_agent_invoker_for_testing(build_invoker())

generated_at = datetime.now(timezone.utc)
run_id = make_run_id()

bundle = fetcher.fetch_bundle(
    db_identifier=${JSON.stringify(body.db_identifier)},
    engine=${JSON.stringify(engine)},
    until=generated_at,
)

md, run = render_report(
    bundle=bundle,
    db_identifier=${JSON.stringify(body.db_identifier)},
    engine=${JSON.stringify(engine)},
    cadence=${JSON.stringify(cadence)},
    run_id=run_id,
    generated_at=generated_at,
)

# Persist to the (in-memory / S3) archive so the run shows up in /reports.
archive.persist(run, {"report.md": md.encode("utf-8")})

print(json.dumps({
    "run_id": run.run_id,
    "status": run.status,
    "section_failures": run.section_failures,
    "markdown": md,
    "engine": run.engine,
    "cadence": run.cadence,
    "generated_at": run.generated_at.isoformat(),
}))
`,
      { timeoutMs: 120_000 },
    );
    return NextResponse.json(data);
  } catch (err) {
    if (err instanceof PythonBridgeError) {
      return NextResponse.json({ error: err.message }, { status: 503 });
    }
    throw err;
  }
}
