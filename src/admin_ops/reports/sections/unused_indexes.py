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

"""Unused Indexes section."""

from __future__ import annotations

from typing import Mapping

from src.admin_ops.reports.format import fnum, md_table

HEADERS = ["schema", "table", "index", "size_mb", "scans"]


def render(bundle: Mapping[str, object]) -> str:
    rows = bundle.get("unused_indexes") or []
    if not isinstance(rows, list) or not rows:
        return "_No unused indexes detected._"
    out: list[list[object]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        out.append(
            [
                r.get("schema", ""),
                r.get("table", ""),
                r.get("index", ""),
                fnum(r.get("size_mb"), sig=4),
                fnum(r.get("scans"), sig=6),
            ]
        )
    return md_table(HEADERS, out)
