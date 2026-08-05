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

"""Markdown → CSV exporter.

Walks the rendered report Markdown and emits one CSV per table-shaped
section. Header order is fixed in code (mirrors the section's own
HEADERS constant) so P8 holds: the `(query_id, mean_time_sec)` tuple
set is identical across MD/PDF/CSV.
"""

from __future__ import annotations

import io
import re
from typing import Iterable

# Section name -> CSV filename mapping. Section names match the H2
# headers emitted by `generator.render_report`.
_SECTION_FILENAMES = {
    "Top Slow Queries": "top_slow_queries.csv",
    "Blocking Incidents": "blocking_incidents.csv",
    "Unused Indexes": "unused_indexes.csv",
    "Vacuum / UNDO Status": "vacuum_undo_status.csv",
    "Tier 3 Operations in Period": "tier3_ops.csv",
}


def _split_sections(md: str) -> list[tuple[str, str]]:
    """Yield (heading, body) pairs for every `## Heading` block."""
    out: list[tuple[str, str]] = []
    cur_heading: str | None = None
    cur_lines: list[str] = []
    for line in md.splitlines():
        m = re.match(r"^## (.+)$", line.strip())
        if m:
            if cur_heading is not None:
                out.append((cur_heading, "\n".join(cur_lines).strip()))
            cur_heading = m.group(1).strip()
            cur_lines = []
        else:
            if cur_heading is not None:
                cur_lines.append(line)
    if cur_heading is not None:
        out.append((cur_heading, "\n".join(cur_lines).strip()))
    return out


def _parse_md_table(body: str) -> tuple[list[str], list[list[str]]] | None:
    """Parse a markdown table into headers and rows. Returns None when the
    body is a placeholder (e.g. `_No data._`) or the table is malformed."""
    lines = [l.rstrip() for l in body.splitlines() if l.strip()]
    rows = [l for l in lines if l.startswith("|")]
    if len(rows) < 2:
        return None
    # First row is headers; second row is the alignment separator.
    if not re.match(r"^\|[\s\-|:]+\|$", rows[1].strip()):
        return None

    def _cells(row: str) -> list[str]:
        # Strip the leading and trailing pipes, then split.
        inner = row.strip().strip("|")
        # Split on unescaped pipes.
        parts = re.split(r"(?<!\\)\|", inner)
        return [p.strip().replace("\\|", "|") for p in parts]

    headers = _cells(rows[0])
    data = [_cells(r) for r in rows[2:]]
    return headers, data


def _csv_escape(s: str) -> str:
    if any(ch in s for ch in (",", '"', "\n", "\r")):
        return '"' + s.replace('"', '""') + '"'
    return s


def export_section_csv(headers: list[str], rows: Iterable[list[str]]) -> str:
    out = io.StringIO()
    out.write(",".join(_csv_escape(h) for h in headers) + "\n")
    for row in rows:
        # Pad short rows so column count is stable.
        while len(row) < len(headers):
            row.append("")
        out.write(",".join(_csv_escape(c) for c in row[: len(headers)]) + "\n")
    return out.getvalue()


def export_csvs(md: str) -> dict[str, str]:
    """Return a mapping from CSV filename to its content."""
    out: dict[str, str] = {}
    for heading, body in _split_sections(md):
        if heading not in _SECTION_FILENAMES:
            continue
        parsed = _parse_md_table(body)
        if parsed is None:
            continue
        headers, rows = parsed
        out[_SECTION_FILENAMES[heading]] = export_section_csv(headers, rows)
    return out
