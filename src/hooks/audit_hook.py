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

"""Audit hook — logs every tool execution for compliance."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import boto3

from src.config import settings
from src.tools._helpers import get_tool_tier

logger = logging.getLogger(__name__)


class AuditHook:
    """Log every tool execution to CloudWatch Logs for audit trail.

    Captures: user, tool, input (sanitized), output summary, tier, timestamp.
    Retained for 90 days per NFR-042.
    """

    def __init__(self):
        self._logs_client = boto3.client("logs", region_name=settings.aws_region)
        self._log_group = "/dbops/agent/audit"
        self._session_id: str | None = None
        self._user_id: str | None = None

    def set_session_context(self, session_id: str, user_id: str) -> None:
        """Set the session context for audit logging."""
        self._session_id = session_id
        self._user_id = user_id

    def after_tool_call(
        self,
        tool_name: str,
        tool_input: dict,
        tool_output: Any,
        **kwargs: Any,
    ) -> None:
        """Called after every tool execution — logs the action."""
        tier = get_tool_tier(tool_name)

        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": self._user_id or "unknown",
            "session_id": self._session_id or "unknown",
            "tool_name": tool_name,
            "tier": tier,
            "input": self._sanitize_input(tool_input),
            "output_summary": self._summarize_output(tool_output),
            "success": not self._is_error(tool_output),
        }

        # Log locally
        logger.info(f"AUDIT: {tool_name} (Tier {tier}) by {self._user_id}")

        # Log to CloudWatch
        self._emit_log(audit_entry)

    def _sanitize_input(self, tool_input: dict) -> dict:
        """Remove sensitive data from tool input before logging."""
        sanitized = {}
        sensitive_keys = {"password", "secret", "token", "credentials"}

        for key, value in tool_input.items():
            if any(s in key.lower() for s in sensitive_keys):
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, str) and len(value) > 500:
                sanitized[key] = value[:500] + "...[truncated]"
            else:
                sanitized[key] = value

        return sanitized

    def _summarize_output(self, output: Any) -> str:
        """Create a brief summary of tool output for the audit log."""
        if isinstance(output, dict):
            if "error" in output:
                return f"ERROR: {output['error'][:200]}"
            if "status" in output:
                return f"status={output['status']}"
            # Return keys and counts
            summary_parts = []
            for key, value in output.items():
                if isinstance(value, list):
                    summary_parts.append(f"{key}: {len(value)} items")
                elif isinstance(value, (int, float)):
                    summary_parts.append(f"{key}={value}")
            return "; ".join(summary_parts[:5]) if summary_parts else "ok"
        return str(output)[:200]

    def _is_error(self, output: Any) -> bool:
        """Check if the tool output indicates an error."""
        if isinstance(output, dict):
            return "error" in output
        return False

    def _emit_log(self, entry: dict) -> None:
        """Emit an audit log entry to CloudWatch Logs."""
        try:
            import time

            self._logs_client.put_log_events(
                logGroupName=self._log_group,
                logStreamName=self._session_id or "default",
                logEvents=[
                    {
                        "timestamp": int(time.time() * 1000),
                        "message": json.dumps(entry, default=str),
                    }
                ],
            )
        except Exception as e:
            # Don't let audit logging failures break the agent
            logger.warning(f"Failed to emit audit log: {e}")
