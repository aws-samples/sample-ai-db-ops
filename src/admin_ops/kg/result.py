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

"""Shared ``GraphResult`` model (R5.7).

Design note on placement
-------------------------
The design sketches ``GraphResult`` inside ``query.py`` (Component 5), but
``store.py`` (Component 4) needs it for ``neighbors`` in Phase 3 — before
``query.py`` exists. To avoid a circular import (store <-> query), the minimal
``GraphResult`` lives in this tiny standalone module. Both ``store.py`` (now)
and ``query.py`` (Phase 5) import it from here, so neither imports the other.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.admin_ops.kg.model import GraphEdge, GraphNode


class GraphResult(BaseModel):
    """A bounded set of nodes/edges returned by a traversal or query (R5.7)."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    focus: str | None = None
    window: dict = {}
