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

"""Top Slow Queries section."""

from __future__ import annotations

from typing import Mapping

from src.admin_ops.reports.format import fnum, md_table

# Stable header order — used for both Markdown rendering and CSV extraction (P8).
HEADERS = ["query_id", "preview", "calls", "mean_time_sec", "total_time_sec"]


def render(bundle: Mapping[str, object]) -> str:
    rows = bundle.get("top_slow_queries") or []
    if not isinstance(rows, list) or not rows:
        return "_No slow queries detected during the report period._"
    out_rows: list[list[object]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        out_rows.append(
            [
                r.get("query_id", ""),
                r.get("preview", ""),
                fnum(r.get("calls"), sig=6),
                fnum(r.get("mean_time_sec"), sig=4),
                fnum(r.get("total_time_sec"), sig=4),
            ]
        )
    return md_table(HEADERS, out_rows)
