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

// Caller-identity guard for routes that are not admin-only.
//
// `withAdminGuard` (./admin.ts) resolves Admin_Role for privileged admin
// operations. Some routes are legitimately used by ordinary application users —
// file upload feeding the data-load tools, and report export — so requiring
// Admin_Role there would break their intended flow. They still must not be
// anonymous, because they write to S3 and read report content.
//
// This guard therefore enforces the weaker-but-correct property for those
// routes: the caller must present a well-formed identity, the identity is
// recorded on the audit trail, and anonymous requests are refused. It fails
// closed on a missing or malformed id.
//
// SCOPE NOTE FOR DEPLOYERS: the identity here is an application-level
// `x-user-id`, not a verified principal. This sample is intended to run behind
// an authenticating front door (ALB/OIDC, Amazon Cognito, IAM-signed access, or
// equivalent) that establishes and injects that header. Do not expose these
// routes directly to untrusted networks.

import { NextRequest, NextResponse } from "next/server";

import { auditEmit } from "@/lib/auth/admin";

/** Accept a conservative identity charset; reject anything else. */
const USER_ID_PATTERN = /^[A-Za-z0-9._@-]{1,128}$/;

export function readUserId(req: NextRequest): string {
  return (
    req.headers.get("x-user-id") ??
    req.cookies.get("user_id")?.value ??
    ""
  );
}

export function isValidUserId(userId: string): boolean {
  return USER_ID_PATTERN.test(userId);
}

/**
 * Run `handler` only for a caller presenting a well-formed identity.
 *
 * Returns 401 without invoking the handler when the identity is absent or
 * malformed, and records every decision on the audit trail.
 */
export async function withIdentifiedUser<T>(
  req: NextRequest,
  op: string,
  handler: (userId: string) => Promise<T> | T,
): Promise<T | NextResponse> {
  const userId = readUserId(req);

  if (!isValidUserId(userId)) {
    auditEmit({ op, user: userId || "<anonymous>", outcome: "deny", context: "invalid_user_id" });
    return NextResponse.json(
      { error: "missing or invalid user_id" },
      { status: 401 },
    );
  }

  auditEmit({ op, user: userId, outcome: "allow" });
  return handler(userId);
}
