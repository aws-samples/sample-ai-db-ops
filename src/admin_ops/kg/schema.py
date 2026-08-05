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

"""Closed graph schema sets + schema parser/printer (R3.1, R3.2, R3.3, R3.9).

This module defines the *closed* node-type and edge-type sets for the DBA
knowledge graph. They extend the ``admin-ops-console`` sets with ``Ticket``
(node) and ``BELONGS_TO`` (edge). Any type outside these closed sets is
rejected by :func:`parse_schema` with a structured error naming the offending
type (R3.3).

``parse_schema``/``print_schema`` follow the exact shape of
``change_event.py::parse``/``print_event``: ``print_schema`` emits canonical
JSON with ``sort_keys=True`` and fixed separators, and additionally sorts
``node_types`` and ``edge_types`` each ascending, so the round-trip
``parse_schema(print_schema(parse_schema(s))) == parse_schema(s)`` holds
deterministically (P-KG3, R3.9).
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, field_validator

# Closed sets. Extends the admin-ops-console sets with Ticket and BELONGS_TO.
NODE_TYPES: frozenset[str] = frozenset(
    {
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
    }
)
EDGE_TYPES: frozenset[str] = frozenset(
    {
        "OWNS",
        "RUNS_AGAINST",
        "EXECUTES",
        "LOADS_TEMPLATE",
        "MODIFIED_BY",
        "CAUSED_BY",
        "BELONGS_TO",
    }
)


def is_known_node_type(t: str) -> bool:
    """Return True iff ``t`` is a member of the closed node-type set."""
    return t in NODE_TYPES


def is_known_edge_type(t: str) -> bool:
    """Return True iff ``t`` is a member of the closed edge-type set."""
    return t in EDGE_TYPES


class GraphSchema(BaseModel):
    """A graph schema description: node types and edge types.

    Both lists are validated as subsets of the closed sets (R3.1, R3.2). Any
    unknown type raises ``ValueError`` naming the offending type (R3.3).
    """

    model_config = ConfigDict(extra="forbid")

    node_types: list[str]
    edge_types: list[str]

    @field_validator("node_types")
    @classmethod
    def _node_types_known(cls, v: list[str]) -> list[str]:
        for t in v:
            if not is_known_node_type(t):
                raise ValueError(f"unknown node type: {t!r}")
        # Canonical (sorted ascending) so the parser/printer round-trip is
        # deterministic and order-independent (P-KG3, R3.9).
        return sorted(v)

    @field_validator("edge_types")
    @classmethod
    def _edge_types_known(cls, v: list[str]) -> list[str]:
        for t in v:
            if not is_known_edge_type(t):
                raise ValueError(f"unknown edge type: {t!r}")
        return sorted(v)


def parse_schema(text: str | dict) -> GraphSchema:
    """Parse a schema description into a validated :class:`GraphSchema`.

    Accepts a JSON string or a dict of the shape
    ``{"node_types": [...], "edge_types": [...]}``. Rejects any type outside
    the closed sets with a structured ``ValueError`` naming the offending type
    (R3.3). Raises ``json.JSONDecodeError`` for malformed JSON strings.
    """
    if isinstance(text, str):
        data = json.loads(text)
    elif isinstance(text, dict):
        data = text
    else:  # pragma: no cover - defensive guard
        raise TypeError(f"parse_schema expects dict or str, got {type(text).__name__}")
    return GraphSchema.model_validate(data)


def print_schema(schema: GraphSchema) -> str:
    """Serialize a :class:`GraphSchema` to canonical, deterministic JSON.

    ``node_types`` and ``edge_types`` are each sorted ascending and the JSON
    is emitted with ``sort_keys=True`` and fixed separators, so the output is
    stable and ``parse_schema(print_schema(parse_schema(s))) ==
    parse_schema(s)`` holds (P-KG3, R3.9).
    """
    payload = {
        "node_types": sorted(schema.node_types),
        "edge_types": sorted(schema.edge_types),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
