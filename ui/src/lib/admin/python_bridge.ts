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

// Tiny wrapper around `child_process.exec` that runs a Python snippet
// against `src.admin_ops.*` and returns the parsed JSON stdout.
//
// Mirrors the pattern used by `/api/invoke` and `/api/admin/resolve-admin`
// — the UI server stays JS, all backend logic is Python.

import { exec } from "child_process";
import { promisify } from "util";
import { mkdtemp, writeFile, rm } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";

import { redactForLog, redactStderr } from "@/lib/redact";

const execAsync = promisify(exec);
const PYTHON = process.env.PYTHON_BIN ?? "python3";

export interface PyCallOptions {
  /**
   * Hard timeout in milliseconds. Defaults to 30s.
   */
  timeoutMs?: number;
}

/**
 * A bridge call failed.
 *
 * `message` is deliberately generic and safe to return to a caller. Routes
 * surface it directly (`{ error: err.message }`), so it must not carry
 * diagnostics: Node's `exec` puts the whole command line *and* the child's
 * stderr into its own error message, which for this bridge means a Python
 * traceback containing the failing statement and its bound values. Full detail
 * goes to the operator log instead, and `stderr` holds a redacted tail for any
 * caller that wants a hint.
 */
export class PythonBridgeError extends Error {
  constructor(
    public readonly stderr: string = "",
    message = "Backend call failed.",
  ) {
    super(message);
    this.name = "PythonBridgeError";
  }
}

function repoRoot(): string {
  // ui/ is a sibling of src/admin_ops/. The Next.js process runs from
  // ui/, so the repo root is one level up.
  return process.cwd().replace(/\/ui\/?$/, "");
}

/**
 * Build a Python script that imports admin_ops and runs the supplied
 * `pythonExpr` (which must `print(json.dumps(...))` its result).
 */
export async function callPython<T>(
  pythonExpr: string,
  opts: PyCallOptions = {},
): Promise<T> {
  // The script is written to a private directory rather than a predictable path
  // in the shared temp directory. mkdtemp creates it with mode 0700 and a name
  // drawn from the platform CSPRNG, so another local user can neither read the
  // script (which carries the query body) nor pre-create the path to influence
  // what gets executed.
  const scriptDir = await mkdtemp(join(tmpdir(), "dbops-bridge-"));
  const scriptPath = join(scriptDir, "call.py");
  const root = repoRoot();
  const wrapped = `
import sys, json
sys.path.insert(0, ${JSON.stringify(root)})

${pythonExpr}
`;
  await writeFile(scriptPath, wrapped);
  try {
    const { stdout, stderr } = await execAsync(`${PYTHON} ${scriptPath}`, {
      timeout: opts.timeoutMs ?? 30_000,
      env: { ...process.env, PYTHONPATH: root },
    });
    if (stderr) {
      // Stderr is informational unless stdout is unparsable. It is redacted
      // before logging because a traceback can carry the failing statement,
      // bound parameter values, or a connection string.
      // eslint-disable-next-line no-console
      console.warn("[python_bridge stderr]", redactStderr(stderr));
    }
    // stdout is the transport for the call's return value, not a log sink: it
    // is parsed here and never written anywhere. Only stderr is logged.
    return JSON.parse(stdout.trim()) as T;
  } catch (err) {
    // exec embeds the command line and the child's stderr in err.message, so
    // the raw value is not safe to propagate. Redact for the log, and hand the
    // caller a generic message.
    const childStderr =
      err && typeof err === "object" && "stderr" in err
        ? String((err as { stderr?: unknown }).stderr ?? "")
        : "";
    // eslint-disable-next-line no-console
    console.error(
      "[python_bridge] call failed:",
      redactForLog(err instanceof Error ? err.message : String(err)),
    );
    throw new PythonBridgeError(redactStderr(childStderr));
  } finally {
    await rm(scriptDir, { recursive: true, force: true }).catch(() => {});
  }
}
