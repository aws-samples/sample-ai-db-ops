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

// Session identifiers for AgentCore runtime invocations.
//
// The id is what ties a sequence of turns to one agent conversation, so it must
// not be guessable: anyone who can predict it could address an existing
// conversation. That rules out `Date.now()` and `Math.random()` — a timestamp is
// public and `Math.random()` is not a cryptographic generator, so its output is
// predictable from observed values.
//
// `crypto.randomUUID()` draws from the platform CSPRNG and is available in
// browsers on a secure context (including localhost) and in Node 19+.

/** AgentCore requires a runtime session id of at least 33 characters. */
const MIN_LENGTH = 33;

const PREFIX = "dbops-session-";

/**
 * Return a fresh, unpredictable session id.
 *
 * The prefix is cosmetic — it makes ids recognisable in logs. The entropy comes
 * entirely from `crypto.randomUUID()`, whose 36 characters already satisfy
 * AgentCore's minimum on their own.
 */
export function newSessionId(): string {
  const id = `${PREFIX}${crypto.randomUUID()}`;
  if (id.length < MIN_LENGTH) {
    // Unreachable with a real UUID; guards against the constant drifting.
    throw new Error(
      `Session id must be at least ${MIN_LENGTH} characters, got ${id.length}.`,
    );
  }
  return id;
}
