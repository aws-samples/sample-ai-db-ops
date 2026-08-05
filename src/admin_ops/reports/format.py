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

"""Deterministic formatting helpers used by the report generator.

Required for P7: two runs over the same input bundle produce
byte-identical Markdown.

Validates: requirement R3.19, property P7.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def fnum(x: Any, sig: int = 6) -> str:
    """Format a number with `sig` significant digits, with stable output.

    Examples:
        fnum(0.000123)  -> "0.000123"
        fnum(123.4567)  -> "123.457"
        fnum(0)         -> "0"
        fnum(None)      -> "—"
    """
    if x is None:
        return "—"
    if isinstance(x, bool):
        # bool is a subclass of int; format as the boolean for clarity.
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        if isinstance(x, float) and (x != x):  # NaN
            return "NaN"
        return f"{x:.{sig}g}"
    return str(x)


def jdumps(obj: Any) -> str:
    """JSON dump with stable key order — used for fixture serialization."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def utc_isoformat(ts: datetime) -> str:
    """ISO-8601 UTC formatter used in the report header."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def md_escape_pipe(value: Any) -> str:
    """Escape `|` characters inside table cells so Markdown stays valid."""
    s = str(value) if value is not None else ""
    return s.replace("|", "\\|").replace("\n", " ")


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Render a Markdown table with stable column order and escaped pipes."""
    out: list[str] = []
    out.append("| " + " | ".join(md_escape_pipe(h) for h in headers) + " |")
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        cells = [md_escape_pipe(c) for c in row]
        # Pad to header width so empty rows stay aligned.
        while len(cells) < len(headers):
            cells.append("")
        out.append("| " + " | ".join(cells[: len(headers)]) + " |")
    return "\n".join(out)
