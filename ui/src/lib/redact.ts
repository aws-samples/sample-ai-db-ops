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

// Redaction for text that is about to be written to a log.
//
// The UI shells out to Python for the admin and DBA surfaces. A Python
// traceback on stderr can contain the failing SQL statement, bound parameter
// values, or a connection string — so stderr is not safe to log verbatim.
//
// These helpers strip the parts most likely to carry data and bound the length,
// leaving enough signal (exception class, file, line) to diagnose a failure.

// `key=value` / `key: value` pairs whose value must not be logged.
// Positional groups (not named) to stay compatible with the ES2017 target.
// Longer alternatives are listed before their shorter prefixes so that, for
// example, `access_token` matches as a whole rather than just `token`.
const SENSITIVE_ASSIGNMENT = new RegExp(
  "(" +
    [
      // Passwords and passphrases
      "passphrase",
      "password",
      "passwd",
      "pwd",
      // Tokens
      "(?:access|refresh|id|auth|bearer|session|csrf|xsrf)[_-]?token",
      "token",
      // Keys
      "(?:api|access|secret|private|public|encryption|signing)[_-]?key",
      // Secrets and credentials
      "(?:client[_-]?)?secret",
      "credentials?",
      "authorization",
      "auth",
      // Session and cookie identifiers
      "session[_-]?id",
      "sessionid",
      "session",
      "cookie",
      // Signatures and AWS-shaped material
      "signature",
      "x-amz-security-token",
      "aws[_-]?session[_-]?token",
      "aws[_-]?secret[_-]?access[_-]?key",
    ].join("|") +
    ")(\\s*[:=]\\s*)(\\S+)",
  "gi",
);

/** Quoted literals typically hold the user data that triggered the error. */
const QUOTED_LITERAL = /'[^']*'|"[^"]*"/g;

/**
 * Return the exception class name only, with no message.
 *
 * Caller-facing responses use this instead of the message, because driver and
 * SDK error text quotes the offending statement, key, or bucket.
 */
export function errorType(error: unknown): string {
  if (error instanceof Error) return error.name || "Error";
  return typeof error;
}

/**
 * Redact secret-looking assignments and quoted literals, collapse whitespace,
 * and truncate.
 */
export function redactForLog(text: unknown, maxLen = 300): string {
  if (text === null || text === undefined) return "";
  // Accepts an Error (or anything) so call sites can hand over a caught value
  // directly without stringifying it unsafely first.
  const raw =
    text instanceof Error
      ? `${text.name}: ${text.message}`
      : typeof text === "string"
        ? text
        : String(text);
  if (!raw) return "";
  let out = raw.replace(SENSITIVE_ASSIGNMENT, (_m, key, sep) => `${key}${sep}[redacted]`);
  out = out.replace(QUOTED_LITERAL, "'[redacted]'");
  out = out.split(/\s+/).join(" ").trim();
  if (out.length > maxLen) out = `${out.slice(0, maxLen)}…[truncated]`;
  return out;
}

/**
 * Strip secret-shaped assignments only, preserving everything else verbatim.
 *
 * For text a human is meant to read back — the prompt and response shown in
 * the trace panel's Logs tab. {@link redactForLog} is deliberately not used
 * there: it also replaces every quoted literal and collapses whitespace, which
 * would turn `describe the "customers" table` into
 * `describe the '[redacted]' table` and make the panel useless.
 *
 * The residual risk this does address is narrow but real: an operator can paste
 * a connection string or password into the chat, and the trace panel supports
 * copying its contents to the clipboard, so that value could leave the browser.
 */
export function redactSecretAssignments(text: string): string {
  if (!text) return "";
  return text.replace(SENSITIVE_ASSIGNMENT, (_m, key, sep) => `${key}${sep}[redacted]`);
}

/**
 * Summarize a stderr stream for logging: keep only the last few lines, redacted.
 * Python puts the exception type and message last, which is the useful part.
 */
export function redactStderr(stderr: string, keepLines = 2): string {
  if (!stderr) return "";
  const tail = stderr.trim().split("\n").slice(-keepLines).join(" | ");
  return redactForLog(tail);
}
