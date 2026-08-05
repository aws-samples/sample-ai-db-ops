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

"""Unit tests for schema closed-set membership and unknown-type rejection.

Covers R3.1 (node types), R3.2 (edge types), R3.3 (reject unknown types with a
structured error naming the offending type).
"""

from __future__ import annotations

import json

import pytest

from src.admin_ops.kg.schema import (
    EDGE_TYPES,
    NODE_TYPES,
    GraphSchema,
    is_known_edge_type,
    is_known_node_type,
    parse_schema,
    print_schema,
)


def test_closed_node_set_exact() -> None:
    assert NODE_TYPES == frozenset(
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


def test_closed_edge_set_exact() -> None:
    assert EDGE_TYPES == frozenset(
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


@pytest.mark.parametrize("t", sorted(NODE_TYPES))
def test_every_node_type_is_known(t: str) -> None:
    assert is_known_node_type(t) is True


@pytest.mark.parametrize("t", sorted(EDGE_TYPES))
def test_every_edge_type_is_known(t: str) -> None:
    assert is_known_edge_type(t) is True


def test_unknown_node_type_is_not_known() -> None:
    assert is_known_node_type("Nonsense") is False


def test_unknown_edge_type_is_not_known() -> None:
    assert is_known_edge_type("FROBNICATES") is False


def test_parse_schema_rejects_unknown_node_type_naming_it() -> None:
    payload = {"node_types": ["Account", "Wombat"], "edge_types": ["OWNS"]}
    with pytest.raises(ValueError) as excinfo:
        parse_schema(payload)
    assert "Wombat" in str(excinfo.value)


def test_parse_schema_rejects_unknown_edge_type_naming_it() -> None:
    payload = {"node_types": ["Account"], "edge_types": ["OWNS", "ZAPS"]}
    with pytest.raises(ValueError) as excinfo:
        parse_schema(payload)
    assert "ZAPS" in str(excinfo.value)


def test_parse_schema_accepts_json_string() -> None:
    text = json.dumps({"node_types": ["Table", "Database"], "edge_types": ["BELONGS_TO"]})
    schema = parse_schema(text)
    # Parsed lists are canonical (sorted ascending) per P-KG3.
    assert schema.node_types == ["Database", "Table"]
    assert schema.edge_types == ["BELONGS_TO"]


def test_parse_schema_accepts_empty_lists() -> None:
    schema = parse_schema({"node_types": [], "edge_types": []})
    assert schema.node_types == []
    assert schema.edge_types == []


def test_print_schema_sorts_each_list_ascending() -> None:
    schema = GraphSchema(
        node_types=["Ticket", "Account", "Database"],
        edge_types=["OWNS", "BELONGS_TO"],
    )
    out = print_schema(schema)
    payload = json.loads(out)
    assert payload["node_types"] == ["Account", "Database", "Ticket"]
    assert payload["edge_types"] == ["BELONGS_TO", "OWNS"]
    # Canonical separators (no spaces).
    assert ", " not in out
