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

"""Vacuum / UNDO Status section."""

from __future__ import annotations

from typing import Mapping

from src.admin_ops.reports.format import fnum, md_table

HEADERS = ["object", "metric", "value"]


def render(bundle: Mapping[str, object]) -> str:
    rows = bundle.get("vacuum_undo_status") or []
    if not isinstance(rows, list) or not rows:
        return "_No vacuum or UNDO findings during the report period._"
    out: list[list[object]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        out.append(
            [
                r.get("object", ""),
                r.get("metric", ""),
                fnum(r.get("value")),
            ]
        )
    return md_table(HEADERS, out)
