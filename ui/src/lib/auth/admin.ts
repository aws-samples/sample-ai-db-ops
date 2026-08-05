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

// Admin-role middleware for privileged Next.js API routes.
//
// Reads `x-user-id` from the incoming request, validates length, then asks
// the admin source of truth whether the user has the Admin_Role. The source
// of truth is the Python `src/admin_ops/admin/role.py::is_admin` lookup
// against the `dbops-admins` DynamoDB table (design.md, decision #1). The UI
// reaches it through the existing internal route `/api/admin/resolve-admin`
// (the same `python_bridge` / `/api/invoke` indirection the rest of the UI
// uses), so this middleware stays pure JS and never embeds an account ID,
// table ARN, or region literal — those are resolved server-side in Python
// from env / `config.yaml` (R7.1, R7.2).
//
// Behaviour matches the `withAdminGuard` snippet in design.md section 6
// exactly:
//   - 401 {error:"missing or invalid user_id"} when `x-user-id` is missing,
//     empty, or longer than 128 chars (no audit emit on this path — the
//     design snippet emits only on the unreachable and deny paths).
//   - 503 {error:"admin source unreachable"} + auditEmit(outcome:"unreachable")
//     when `resolveAdmin` throws.
//   - 403 {error:"forbidden"} + auditEmit(outcome:"deny") for a non-admin.
//   - otherwise auditEmit(outcome:"allow") and run the handler.
//
// `resolveAdmin` wraps the source lookup in a process-local 60s TTL cache so
// role resolution stays under the 500 ms budget (R6.1).
//
// Validates: requirements R6.6, R6.7, R6.8 (and supports R6.1, R6.4).

import { NextRequest, NextResponse } from "next/server";

/** Outcome recorded on the audit trail for an admin check. */
export type AdminCheckOutcome = "allow" | "deny" | "unreachable";

export interface AuditEntry {
  /** Operation identifier. Always `"admin_check"` for this middleware. */
  op: string;
  /** The `user_id` the check was resolved against. */
  user: string;
  /** Result of the admin check. */
  outcome: AdminCheckOutcome;
  /** ISO-8601 UTC timestamp. Filled by `auditEmit` when omitted. */
  timestamp?: string;
  /** Optional route context (the privileged op the guard was protecting). */
  context?: string;
}

// ─── Audit emission ─────────────────────────────────────────────────────────

let _emit: (entry: AuditEntry) => void = (entry) => {
  // Default sink: structured stdout line. The agent audit pipeline scrapes
  // these; tests replace the sink with a recorder via
  // `setAuditEmitterForTesting`.
  // eslint-disable-next-line no-console
  console.log("[audit]", JSON.stringify(entry));
};

/**
 * Emit one audit entry for an admin check. Stamps a UTC timestamp when the
 * caller did not supply one.
 */
export function auditEmit(entry: AuditEntry): void {
  _emit({ timestamp: new Date().toISOString(), ...entry });
}

/** Swap the audit sink (tests). Pass `null` to restore the default. */
export function setAuditEmitterForTesting(
  emit: ((entry: AuditEntry) => void) | null,
): void {
  _emit =
    emit ??
    ((entry) => {
      // eslint-disable-next-line no-console
      console.log("[audit]", JSON.stringify(entry));
    });
}

// ─── Admin resolution (60s TTL cache over the source of truth) ──────────────

type AdminSource = (userId: string) => Promise<boolean>;

/**
 * Underlying admin source lookup. Hits the internal `/api/admin/resolve-admin`
 * route, which proxies to the Python `is_admin` over the `dbops-admins` table.
 * Throws on any non-2xx response so the guard can translate it to a 503.
 */
let _adminSource: AdminSource = async (userId) => {
  const port = process.env.PORT ?? "3001";
  const res = await fetch(`http://127.0.0.1:${port}/api/admin/resolve-admin`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-internal-call": "1" },
    body: JSON.stringify({ user_id: userId }),
  });
  if (!res.ok) {
    throw new Error(`admin source returned ${res.status}`);
  }
  const data = (await res.json()) as { is_admin?: boolean };
  return Boolean(data.is_admin);
};

/**
 * Swap the underlying admin source (tests). Pass `null` to restore the
 * default HTTP-backed source. Swapping also clears the resolution cache.
 */
export function setAdminResolverForTesting(source: AdminSource | null): void {
  _adminSource = source ?? (async () => false);
  _cache.clear();
}

const CACHE_TTL_MS = 60_000;
const _cache = new Map<string, { isAdmin: boolean; ts: number }>();

/**
 * Resolve `user_id` to `is_admin`, backed by a process-local 60s TTL cache
 * (R6.1). Propagates errors from the underlying source so `withAdminGuard`
 * can deny with a 503 (R6.7).
 */
export async function resolveAdmin(userId: string): Promise<boolean> {
  const cached = _cache.get(userId);
  if (cached && Date.now() - cached.ts < CACHE_TTL_MS) {
    return cached.isAdmin;
  }
  const isAdmin = await _adminSource(userId);
  _cache.set(userId, { isAdmin, ts: Date.now() });
  return isAdmin;
}

/** Clear the resolution cache (tests, and on grant/revoke invalidation). */
export function resetAdminCacheForTesting(): void {
  _cache.clear();
}

// ─── Guard ──────────────────────────────────────────────────────────────────

type Handler<T> = (userId: string) => Promise<T> | T;

function isValidUserId(userId: string): boolean {
  return userId.length >= 1 && userId.length <= 128;
}

/**
 * Wrap a privileged route handler with the Admin_Role check.
 *
 * The primary signature matches design.md exactly:
 *   `withAdminGuard(req, handler)`
 *
 * An optional `op` form is also accepted for callers that want the protected
 * operation recorded as audit `context`:
 *   `withAdminGuard(req, op, handler)`
 */
export async function withAdminGuard<T>(
  req: NextRequest,
  handler: Handler<T>,
): Promise<T | NextResponse>;
export async function withAdminGuard<T>(
  req: NextRequest,
  op: string,
  handler: Handler<T>,
): Promise<T | NextResponse>;
export async function withAdminGuard<T>(
  req: NextRequest,
  opOrHandler: string | Handler<T>,
  maybeHandler?: Handler<T>,
): Promise<T | NextResponse> {
  const op = typeof opOrHandler === "string" ? opOrHandler : undefined;
  const handler =
    typeof opOrHandler === "function" ? opOrHandler : (maybeHandler as Handler<T>);

  const userId = req.headers.get("x-user-id") ?? "";

  // R6.8: missing / empty / out-of-bounds user_id → 401, no state change.
  // The design snippet does not emit an audit entry on this path.
  if (!isValidUserId(userId)) {
    return NextResponse.json(
      { error: "missing or invalid user_id" },
      { status: 401 },
    );
  }

  // R6.7: source-of-truth error during resolution → 503, audit, no mutation.
  let isAdmin: boolean;
  try {
    isAdmin = await resolveAdmin(userId);
  } catch {
    auditEmit({ op: "admin_check", user: userId, outcome: "unreachable", context: op });
    return NextResponse.json(
      { error: "admin source unreachable" },
      { status: 503 },
    );
  }

  // R6.4: non-admin → 403, audit, no mutation.
  if (!isAdmin) {
    auditEmit({ op: "admin_check", user: userId, outcome: "deny", context: op });
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  // Allowed — record the grant and run the protected handler.
  auditEmit({ op: "admin_check", user: userId, outcome: "allow", context: op });
  return handler(userId);
}
