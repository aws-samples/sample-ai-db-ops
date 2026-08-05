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

// Client-side identity for calls to guarded API routes.
//
// Server-side guards (`withAdminGuard`, `withIdentifiedUser`) read the caller
// identity from the `x-user-id` request header only — they deliberately do not
// fall back to an environment default, because a server-side default would mean
// an anonymous request silently acquires an identity.
//
// Every browser call to a guarded route therefore has to send the header. This
// helper is the single place that decides what it contains, so call sites cannot
// drift apart or forget it.
//
// SCOPE NOTE FOR DEPLOYERS: `NEXT_PUBLIC_USER_ID` is a development convenience,
// not authentication — a browser can set any header it likes. Deploy this sample
// behind an authenticating proxy (ALB/OIDC, Amazon Cognito, or equivalent) that
// establishes the user and injects a trusted identity header server-side.

/** Identity used for calls to guarded routes. */
export function currentUserId(): string {
  return process.env.NEXT_PUBLIC_USER_ID || "dbops-user";
}

/**
 * Merge the identity header into any additional headers for a `fetch` call.
 *
 * Usage: `fetch(url, { headers: withUserHeader({ "content-type": "application/json" }) })`
 */
export function withUserHeader(extra?: Record<string, string>): Record<string, string> {
  return { ...(extra ?? {}), "x-user-id": currentUserId() };
}
