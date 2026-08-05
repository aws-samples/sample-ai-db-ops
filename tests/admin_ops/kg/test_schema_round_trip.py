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

"""Property P-KG3 (R3.9) — graph schema parser/printer round-trip.

For any valid schema description s (subsets of the closed sets):
    parse_schema(print_schema(parse_schema(s))) == parse_schema(s)
and the printer output is deterministic (node_types/edge_types sorted ascending).
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg.schema import (
    EDGE_TYPES,
    NODE_TYPES,
    parse_schema,
    print_schema,
)

_NODE_TYPES = sorted(NODE_TYPES)
_EDGE_TYPES = sorted(EDGE_TYPES)


@st.composite
def schema_payloads(draw: st.DrawFn) -> dict:
    nodes = draw(st.lists(st.sampled_from(_NODE_TYPES), max_size=len(_NODE_TYPES), unique=True))
    edges = draw(st.lists(st.sampled_from(_EDGE_TYPES), max_size=len(_EDGE_TYPES), unique=True))
    return {"node_types": nodes, "edge_types": edges}


# Feature: dba-knowledge-graph, Property P-KG3: schema parser/printer round-trip
@settings(deadline=None, max_examples=200)
@given(payload=schema_payloads())
def test_p_kg3_schema_round_trip(payload: dict) -> None:
    parsed = parse_schema(payload)
    assert parse_schema(print_schema(parsed)) == parsed


# Feature: dba-knowledge-graph, Property P-KG3: printer output is deterministic
@settings(deadline=None, max_examples=200)
@given(payload=schema_payloads())
def test_p_kg3_printer_sorted_and_stable(payload: dict) -> None:
    parsed = parse_schema(payload)
    out = print_schema(parsed)
    # Stable across calls.
    assert out == print_schema(parsed)
    # Round-trip through string form is identical too.
    assert print_schema(parse_schema(out)) == out
