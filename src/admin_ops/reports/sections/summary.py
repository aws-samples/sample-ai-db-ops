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

"""Summary section: high-level findings."""

from __future__ import annotations

from typing import Mapping


def render(bundle: Mapping[str, object]) -> str:
    summary = bundle.get("summary") or {}
    if not isinstance(summary, Mapping):
        return "_No summary fields available._"
    lines: list[str] = []
    for key in sorted(summary.keys()):
        lines.append(f"- **{key}**: {summary[key]}")
    return "\n".join(lines) if lines else "_No summary fields available._"
