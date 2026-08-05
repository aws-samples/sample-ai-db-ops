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

"""Capacity Headroom section."""

from __future__ import annotations

from typing import Mapping

from src.admin_ops.reports.format import fnum, md_table

HEADERS = ["metric", "value", "unit"]


def render(bundle: Mapping[str, object]) -> str:
    obj = bundle.get("capacity_headroom") or {}
    if not isinstance(obj, Mapping) or not obj:
        return "_No capacity headroom data available._"
    out: list[list[object]] = []
    for key in sorted(obj.keys()):
        v = obj[key]
        if isinstance(v, Mapping):
            out.append([key, fnum(v.get("value")), v.get("unit", "")])
        else:
            out.append([key, fnum(v), ""])
    return md_table(HEADERS, out)
