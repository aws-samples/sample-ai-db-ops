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

"""Tier 3 Operations in Period section.

Sourced from the existing audit log (R3.3). The bundle key matches what
the audit-log fetcher emits.
"""

from __future__ import annotations

from typing import Mapping

from src.admin_ops.reports.format import md_table

HEADERS = ["timestamp", "actor", "tool", "outcome", "summary"]


def render(bundle: Mapping[str, object]) -> str:
    rows = bundle.get("tier3_ops") or []
    if not isinstance(rows, list) or not rows:
        return "_No Tier 3 operations executed during the report period._"
    out: list[list[object]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        out.append(
            [
                r.get("timestamp", ""),
                r.get("actor", ""),
                r.get("tool", ""),
                r.get("outcome", ""),
                r.get("summary", ""),
            ]
        )
    return md_table(HEADERS, out)
