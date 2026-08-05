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

import { NextRequest, NextResponse } from "next/server";
import { exec } from "child_process";
import { promisify } from "util";
import { writeFile, unlink } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";

import { errorType, redactForLog, redactStderr } from "@/lib/redact";

const execAsync = promisify(exec);

// Agent runtime ARNs are read from environment variables. Set them in
// `ui/.env.local` after running `agentcore deploy` for each engine. See
// `ui/.env.local.example` for the full list.
const AGENT_ARNS: Record<string, string> = {
  postgresql: process.env.POSTGRESQL_AGENT_ARN || "",
  mysql: process.env.MYSQL_AGENT_ARN || "",
  oracle: process.env.ORACLE_AGENT_ARN || "",
  dynamodb: process.env.DYNAMODB_AGENT_ARN || "",
};

// Region for invoking AgentCore. We read AGENT_REGION first so a bad ambient
// AWS_REGION export in the launching shell doesn't redirect the agent
// invocation to the wrong region. Falls back to AWS_REGION, then us-east-1.
const REGION = process.env.AGENT_REGION || process.env.AWS_REGION || "us-east-1";
const PYTHON = process.env.PYTHON_BIN || "python3.12";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { prompt, user_id, agent_type, session_id, history, approvals } = body;

    if (!prompt) {
      return NextResponse.json({ error: "Missing prompt" }, { status: 400 });
    }

    const agentArn = AGENT_ARNS[agent_type] || AGENT_ARNS.postgresql;
    if (!agentArn) {
      return NextResponse.json(
        {
          error:
            `No AgentCore runtime ARN configured for agent_type='${agent_type}'. ` +
            `Set ${agent_type.toUpperCase()}_AGENT_ARN in ui/.env.local after running 'agentcore deploy'.`,
        },
        { status: 500 }
      );
    }

    // Build context-aware prompt with conversation history
    let fullPrompt = prompt;
    if (history && history.length > 0) {
      const historyText = history.map((m: { role: string; content: string }) =>
        `${m.role === "user" ? "User" : "Assistant"}: ${m.content}`
      ).join("\n\n");
      fullPrompt = `Previous conversation:\n${historyText}\n\nUser: ${prompt}`;
    }

    // AgentCore requires runtimeSessionId of length >= 33. Pad short IDs.
    let sessionIdForAgent: string | undefined = session_id;
    if (sessionIdForAgent && sessionIdForAgent.length < 33) {
      sessionIdForAgent = (sessionIdForAgent + "-".repeat(33)).slice(0, 33);
    }

    // Tier-3 approval decisions. These originate from an explicit operator
    // action in the UI and are forwarded verbatim to the agent, where the
    // Tier3ApprovalHook matches each one against the exact tool + argument
    // fingerprint it was issued for. Model output never reaches this field.
    const approvalList = Array.isArray(approvals) ? approvals : [];

    // Build the agent payload as JSON in JS, then embed it as a single Python
    // string literal. This avoids hand-mapping JSON types to Python literals.
    const agentPayload = JSON.stringify({
      prompt: fullPrompt,
      user_id: user_id || "anonymous",
      ...(approvalList.length > 0 ? { approvals: approvalList } : {}),
    });

    // Write a temp Python script to avoid shell quoting issues
    const scriptPath = join(tmpdir(), `dbops_invoke_${Date.now()}.py`);
    const script = `
import boto3, json, sys

client = boto3.client("bedrock-agentcore", region_name=${JSON.stringify(REGION)})
payload = ${JSON.stringify(agentPayload)}

params = {
    "agentRuntimeArn": ${JSON.stringify(agentArn)},
    "qualifier": "DEFAULT",
    "payload": payload,
}
${sessionIdForAgent ? `params["runtimeSessionId"] = ${JSON.stringify(sessionIdForAgent)}` : ""}

response = client.invoke_agent_runtime(**params)
body = response["response"].read().decode("utf-8")
parsed = json.loads(body)

if isinstance(parsed, dict) and parsed.get("awaiting_approval"):
    # A Tier-3 operation is pending operator approval. Nothing was executed.
    print(json.dumps({
        "response": None,
        "awaiting_approval": True,
        "pending_approvals": parsed.get("pending_approvals", []),
    }))
    sys.exit(0)

if "response" in parsed and isinstance(parsed["response"], dict):
    content = parsed["response"].get("content", [])
    if content and "text" in content[0]:
        print(json.dumps({"response": content[0]["text"]}))
        sys.exit(0)

print(json.dumps({"response": body}))
`;

    await writeFile(scriptPath, script);

    try {
      const cmd = `${PYTHON} ${scriptPath}`;
      console.log("[/api/invoke] cmd:", cmd, "ARN:", agentArn, "region:", REGION);
      // Force AWS_REGION/AWS_DEFAULT_REGION to the configured REGION so an
      // ambient export in the launching shell can't redirect us to the wrong region.
      const childEnv = {
        ...process.env,
        AWS_REGION: REGION,
        AWS_DEFAULT_REGION: REGION,
      };
      const { stdout, stderr } = await execAsync(cmd, { timeout: 180000, env: childEnv });
      // Redacted: agent stderr can echo the prompt or query results.
      if (stderr) console.log("[/api/invoke] stderr:", redactStderr(stderr));
      const parsed = JSON.parse(stdout.trim());
      return NextResponse.json({
        response: parsed.response,
        awaiting_approval: Boolean(parsed.awaiting_approval),
        pending_approvals: Array.isArray(parsed.pending_approvals)
          ? parsed.pending_approvals
          : [],
        session_id,
        agent_type,
        user_id,
      });
    } finally {
      await unlink(scriptPath).catch(() => {});
    }
  } catch (error: unknown) {
    // Full detail goes to the operator log; the caller gets the exception class
    // only. Filtering the message for lines containing "error" — the previous
    // approach — still forwarded whichever lines matched, and those can quote
    // the generated script, the agent ARN, or the submitted statement. The
    // exception class is enough for the operator to act on, and the log has the
    // rest (M-016).
    console.error("[/api/invoke] invocation failed:", redactForLog(error));
    return NextResponse.json(
      {
        error: `Agent invocation failed (${errorType(error)}). See server logs for detail.`,
        error_type: errorType(error),
      },
      { status: 500 }
    );
  }
}
