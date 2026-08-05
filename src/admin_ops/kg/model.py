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

"""Graph node/edge pydantic models and ``node_id`` helpers (R3.6, R3.7, R3.8, R5.7).

``GraphNode`` and ``GraphEdge`` mirror the ``ChangeEvent`` style: pydantic
``BaseModel`` with ``ConfigDict(extra="forbid")``. ``NodeType`` and ``EdgeType``
are ``Literal``s matching the closed sets in :mod:`schema`.

The ``node_id`` scheme is ``"{type}:{natural_key}"`` (R3.6). Because a natural
key may itself contain ``:`` (e.g. ``Table:database-test:shop.orders``),
:func:`split_node_id` splits on the *first* ``:`` only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal[
    "Account",
    "Principal",
    "Database",
    "Table",
    "Agent",
    "Tool",
    "Template",
    "ChangeEvent",
    "Incident",
    "Ticket",
]
EdgeType = Literal[
    "OWNS",
    "RUNS_AGAINST",
    "EXECUTES",
    "LOADS_TEMPLATE",
    "MODIFIED_BY",
    "CAUSED_BY",
    "BELONGS_TO",
]


class GraphNode(BaseModel):
    """One graph node, keyed by a stable ``node_id`` (R3.6, R3.7, R5.7)."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)  # "{type}:{natural_key}"
    type: NodeType
    label: str  # display label (R5.7)
    props: dict[str, str | int | float | bool | None] = {}


class GraphEdge(BaseModel):
    """A directed edge between two node_ids (R3.4, R3.5, R5.7)."""

    model_config = ConfigDict(extra="forbid")

    edge_type: EdgeType
    source_id: str = Field(min_length=1)  # node_id of source
    target_id: str = Field(min_length=1)  # node_id of target


def make_node_id(node_type: str, natural_key: str) -> str:
    """Return ``"{node_type}:{natural_key}"`` (R3.6).

    Natural keys are deterministic functions of ``ChangeEvent`` fields (or of
    seeded data), so re-deriving the id for the same entity is stable.
    """
    return f"{node_type}:{natural_key}"


def split_node_id(node_id: str) -> tuple[str, str]:
    """Split ``node_id`` into ``(type, natural_key)`` on the FIRST ``:`` only.

    ``"Table:database-test:shop.orders"`` -> ``("Table", "database-test:shop.orders")``.
    Raises ``ValueError`` when ``node_id`` has no ``:`` separator.
    """
    head, sep, tail = node_id.partition(":")
    if not sep:
        raise ValueError(f"node_id missing ':' separator: {node_id!r}")
    return head, tail
