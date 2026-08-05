# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Error text that is safe to persist or return to a caller.

Database drivers routinely put the failing statement — and sometimes the bound
values — into the exception message. ``psycopg2``, for example, includes the
offending SQL and a caret pointing at the syntax error. Writing ``str(exc)``
straight into an audit record, a report, or an HTTP response therefore risks
persisting query text and user data in places with different access controls
than the database itself.

The convention in this project:

* **Audit records, reports, and API responses** carry the exception *type* only,
  via :func:`safe_error`. That is enough to distinguish a timeout from a
  permission error without copying data around.
* **Operator logs** may carry the full exception, via ``logging.exception``,
  because those are already scoped to whoever operates the deployment.
"""

from __future__ import annotations

import re

# Keys whose value must never survive into a log line. Longer alternatives come
# before their shorter prefixes so that, for example, "access_token" matches as a
# whole rather than only its "token" suffix.
#
# Kept deliberately in step with the TypeScript twin in ui/src/lib/redact.ts:
# the UI and the Python backend log the same failures from opposite sides, so a
# key covered in one place and not the other is a gap.
_SENSITIVE_KEYS = (
    # Passwords and passphrases
    "passphrase",
    "password",
    "passwd",
    "pwd",
    # Tokens
    r"(?:access|refresh|id|auth|bearer|session|csrf|xsrf)[_-]?token",
    "token",
    # Keys
    r"(?:api|access|secret|private|public|encryption|signing)[_-]?key",
    # Secrets and credentials
    r"(?:client[_-]?)?secret",
    "credentials?",
    "authorization",
    "auth",
    # Session and cookie identifiers
    r"session[_-]?id",
    "sessionid",
    "session",
    "cookie",
    # Signatures and AWS-shaped material
    "signature",
    "x-amz-security-token",
    r"aws[_-]?session[_-]?token",
    r"aws[_-]?secret[_-]?access[_-]?key",
)

_SENSITIVE_KEY = re.compile(
    r"(?i)(" + "|".join(_SENSITIVE_KEYS) + r")(\s*[:=]\s*)(\S+)"
)
# Quoted literals frequently carry the user data that caused the failure.
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def safe_error(exc: BaseException) -> str:
    """Return the exception type name, with no message content.

    Use for anything persisted or returned to a caller.
    """
    return type(exc).__name__


def redact(text: str, *, max_len: int = 200) -> str:
    """Return ``text`` with secret-looking values and quoted literals removed.

    For the rare case where some detail genuinely helps an operator and the sink
    is not fully trusted. Prefer :func:`safe_error` when a type is sufficient.
    """
    if not text:
        return ""
    # Keep the key and its separator so the line stays readable; drop the value.
    scrubbed = _SENSITIVE_KEY.sub(r"\1\2[redacted]", text)
    scrubbed = _QUOTED.sub("'[redacted]'", scrubbed)
    scrubbed = " ".join(scrubbed.split())
    if len(scrubbed) > max_len:
        scrubbed = scrubbed[:max_len] + "…[truncated]"
    return scrubbed
