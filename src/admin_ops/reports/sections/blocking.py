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

"""Blocking Incidents section."""

from __future__ import annotations

from typing import Mapping

from src.admin_ops.reports.format import fnum, md_table

HEADERS = ["blocker_pid", "victim_pid", "blocker_query", "wait_seconds"]


def render(bundle: Mapping[str, object]) -> str:
    rows = bundle.get("blocking_incidents") or []
    if not isinstance(rows, list) or not rows:
        return "_No blocking incidents during the report period._"
    out: list[list[object]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        out.append(
            [
                r.get("blocker_pid", ""),
                r.get("victim_pid", ""),
                r.get("blocker_query", ""),
                fnum(r.get("wait_seconds"), sig=4),
            ]
        )
    return md_table(HEADERS, out)
