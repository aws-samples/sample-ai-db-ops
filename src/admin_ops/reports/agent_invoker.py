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

"""Runtime agent invoker for the report generator.

Bridges the report fetcher to the live Bedrock AgentCore agents. The
fetcher expects a callable `(engine, tool_name, args) -> Mapping` that
returns the raw tool output. The agents reply with conversational text,
so this module asks each tool to emit ONLY raw JSON in a fenced block,
extracts it, and normalizes the tool-specific key names into the shape
the section shapers in `fetcher.py` expect.

Agent runtime ARNs are read from the environment
(`<ENGINE>_AGENT_ARN`), mirroring the UI's /api/invoke route. When an
ARN is missing or the call fails, the invoker returns `{}` so the
affected section degrades to the "no findings" placeholder (R3.18)
rather than aborting the whole report.

This keeps boto3 import lazy: nothing here touches AWS until
`build_invoker()` is actually called and a tool is invoked.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Mapping

LOG = logging.getLogger(__name__)

_REGION = os.environ.get("AGENT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"

_ARN_ENV = {
    "postgresql": "POSTGRESQL_AGENT_ARN",
    "mysql": "MYSQL_AGENT_ARN",
    "oracle": "ORACLE_AGENT_ARN",
    "dynamodb": "DYNAMODB_AGENT_ARN",
}


def _agent_arn(engine: str) -> str | None:
    env_key = _ARN_ENV.get(engine)
    if not env_key:
        return None
    return os.environ.get(env_key) or None


def _extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a possibly-prose response."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        candidate = m.group(1) if m else None
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _normalize(tool_name: str, data: dict) -> dict:
    """Map a tool's actual response keys to what the fetcher shapers expect."""
    if tool_name == "get_slow_queries":
        rows = (
            data.get("slow_queries")
            or data.get("queries")
            or data.get("rows")
            or []
        )
        norm = []
        for r in rows:
            if not isinstance(r, Mapping):
                continue
            mean_s = r.get("avg_time_sec")
            total_s = r.get("total_time_sec")
            norm.append(
                {
                    "queryid": r.get("queryid") or r.get("query_id"),
                    "query_preview": (r.get("query_text") or r.get("query") or "")[:160],
                    "calls": r.get("calls") or 0,
                    "mean_ms": float(mean_s) * 1000.0 if mean_s is not None else (r.get("mean_ms") or 0),
                    "total_ms": float(total_s) * 1000.0 if total_s is not None else (r.get("total_ms") or 0),
                }
            )
        return {"queries": norm}
    # Other tools already align well enough with the shapers; pass through.
    return data


def build_invoker() -> Callable[[str, str, Mapping[str, Any] | None], Mapping[str, Any]]:
    """Return a `(engine, tool_name, args) -> Mapping` callable.

    The returned function invokes the live agent and returns normalized
    raw tool output, or `{}` on any failure.
    """
    import boto3  # lazy

    client = boto3.client("bedrock-agentcore", region_name=_REGION)

    def _invoke(engine: str, tool_name: str, args: Mapping[str, Any] | None) -> Mapping[str, Any]:
        arn = _agent_arn(engine)
        if not arn:
            LOG.info("no ARN configured for engine=%s; section will be empty", engine)
            return {}
        top_n = ""
        if tool_name == "get_slow_queries":
            top_n = " with top_n=10"
        prompt = (
            f"Call the {tool_name} tool{top_n}. Return ONLY the raw JSON object "
            "the tool produced, inside a ```json code block. No prose, no "
            "commentary, no tables."
        )
        session = (f"report-{engine}-{tool_name}" + "-" * 48)[:48]
        try:
            resp = client.invoke_agent_runtime(
                agentRuntimeArn=arn,
                qualifier="DEFAULT",
                runtimeSessionId=session,
                payload=json.dumps({"prompt": prompt, "user_id": "report-generator"}),
            )
            body = resp["response"].read().decode("utf-8")
            parsed = json.loads(body)
            inner = parsed.get("response", parsed)
            if isinstance(inner, dict):
                content = inner.get("content", [])
                if content and isinstance(content[0], dict) and "text" in content[0]:
                    text = content[0]["text"]
                else:
                    text = body
            else:
                text = str(inner)
            data = _extract_json(text)
            if not isinstance(data, dict):
                return {}
            return _normalize(tool_name, data)
        except Exception as exc:  # noqa: BLE001 - degrade to empty section (R3.18)
            LOG.warning("report invoker failed engine=%s tool=%s: %s", engine, tool_name, exc)
            return {}

    return _invoke
