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

"""Health report section renderers.

Each module exports `render(input_bundle: dict, run: ReportRun) -> str`
that returns the section's Markdown body. Sections that fail produce a
`Section Failed` block (R3.18) rather than crashing the run.
"""

from __future__ import annotations

from typing import Callable, Mapping

from src.admin_ops.reports.sections import (
    blocking,
    capacity,
    summary,
    tier3_ops,
    top_slow_queries,
    unused_indexes,
    vacuum_undo,
)

# Order of sections matches R3.2 verbatim.
SECTIONS: list[tuple[str, Callable[[Mapping[str, object]], str]]] = [
    ("Summary", summary.render),
    ("Top Slow Queries", top_slow_queries.render),
    ("Blocking Incidents", blocking.render),
    ("Unused Indexes", unused_indexes.render),
    ("Capacity Headroom", capacity.render),
    ("Vacuum / UNDO Status", vacuum_undo.render),
    ("Tier 3 Operations in Period", tier3_ops.render),
]
