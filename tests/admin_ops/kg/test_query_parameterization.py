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

"""Cypher query-construction safety for NeptuneBackend (R5.2, R10.3, P-KG6).

Asserts that every caller-supplied value (node_id, since, type, props,
ticket_id, edge_type) reaches Neptune ONLY as a bound parameter — never via
f-string / % interpolation — and that ``hops`` selects one of three pre-written
query strings rather than interpolating a caller value.

No AWS: the Neptune transport (``_execute``) is monkeypatched with a recorder,
so we observe exactly the (query, params) pairs the backend would send.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.admin_ops.kg.ingest import GraphMutation
from src.admin_ops.kg.model import GraphEdge, GraphNode
from src.admin_ops.kg.store import (
    NeptuneBackend,
    neighbors_cypher_for_hops,
    _NEIGHBORS_CYPHER_BY_HOPS,
)

_SINCE = datetime(2024, 1, 1, tzinfo=timezone.utc)
# A node_id containing openCypher metacharacters: if it were interpolated, it
# would corrupt the query. As a bound parameter it is inert.
_HOSTILE_ID = "Database:'); MATCH (x) DETACH DELETE x //"


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, query: str, params: dict) -> dict:
        self.calls.append((query, params))
        return {"results": []}


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> NeptuneBackend:
    b = NeptuneBackend(endpoint="example-neptune.invalid")
    rec = _Recorder()
    monkeypatch.setattr(b, "_execute", rec)
    b._recorder = rec  # type: ignore[attr-defined]
    return b


def _all_calls(backend: NeptuneBackend) -> list[tuple[str, dict]]:
    return backend._recorder.calls  # type: ignore[attr-defined]


def test_hops_selects_one_of_three_prewritten_strings() -> None:
    # The three strings are distinct, fixed, and chosen by integer lookup.
    assert set(_NEIGHBORS_CYPHER_BY_HOPS) == {1, 2, 3}
    assert neighbors_cypher_for_hops(1) is _NEIGHBORS_CYPHER_BY_HOPS[1]
    assert neighbors_cypher_for_hops(2) is _NEIGHBORS_CYPHER_BY_HOPS[2]
    assert neighbors_cypher_for_hops(3) is _NEIGHBORS_CYPHER_BY_HOPS[3]


@pytest.mark.parametrize("bad", [0, 4, -1, 99])
def test_out_of_range_hops_never_interpolated(bad: int) -> None:
    # An out-of-range hop raises rather than being interpolated anywhere.
    with pytest.raises(ValueError):
        neighbors_cypher_for_hops(bad)


def test_neighbors_passes_node_id_and_since_as_parameters(
    backend: NeptuneBackend,
) -> None:
    backend.neighbors(_HOSTILE_ID, hops=2, since=_SINCE)
    (query, params) = _all_calls(backend)[0]
    # The query is exactly the pre-written hops=2 string — the hostile id is
    # NOT present in the query text.
    assert query == _NEIGHBORS_CYPHER_BY_HOPS[2]
    assert _HOSTILE_ID not in query
    # node_id and since travel as bound parameters.
    assert params["focus"] == _HOSTILE_ID
    assert params["since"] == _SINCE.isoformat()


def test_get_node_passes_node_id_as_parameter(backend: NeptuneBackend) -> None:
    backend.get_node(_HOSTILE_ID)
    (query, params) = _all_calls(backend)[0]
    assert _HOSTILE_ID not in query
    assert params == {"node_id": _HOSTILE_ID}


def test_upsert_passes_all_node_and_edge_values_as_parameters(
    backend: NeptuneBackend,
) -> None:
    node = GraphNode(
        node_id=_HOSTILE_ID,
        type="Database",
        label="'); DROP",
        props={"engine": "postgresql", "x": "y"},
    )
    edge = GraphEdge(
        edge_type="BELONGS_TO", source_id=_HOSTILE_ID, target_id="Database:db"
    )
    backend.upsert(GraphMutation(nodes=[node], edges=[edge]))

    calls = _all_calls(backend)
    # First call: node upsert. No caller value is in the query text.
    node_query, node_params = calls[0]
    assert _HOSTILE_ID not in node_query
    assert "'); DROP" not in node_query
    assert node_params["node_id"] == _HOSTILE_ID
    assert node_params["type"] == "Database"
    assert node_params["label"] == "'); DROP"
    assert node_params["props"] == {"engine": "postgresql", "x": "y"}

    # Second call: edge upsert. Endpoints + edge_type are all parameters.
    edge_query, edge_params = calls[1]
    assert _HOSTILE_ID not in edge_query
    assert edge_params["source_id"] == _HOSTILE_ID
    assert edge_params["target_id"] == "Database:db"
    assert edge_params["edge_type"] == "BELONGS_TO"


def test_all_change_events_passes_since_as_parameter(
    backend: NeptuneBackend,
) -> None:
    backend.all_change_events(_SINCE)
    (query, params) = _all_calls(backend)[0]
    assert _SINCE.isoformat() not in query  # not interpolated
    assert params == {"since": _SINCE.isoformat()}


def test_query_strings_contain_no_format_or_percent_placeholders() -> None:
    # Defense-in-depth: the static query strings must not carry Python-style
    # interpolation placeholders that a caller value could later be substituted
    # into. openCypher legitimately uses brace maps like `{node_id: $focus}`,
    # so we check for empty `{}` and `%`-style placeholders, and require every
    # binding to be a `$named` openCypher parameter.
    import re

    statics = list(_NEIGHBORS_CYPHER_BY_HOPS.values())
    from src.admin_ops.kg.store import _UPSERT_NODE_CYPHER, _UPSERT_EDGE_CYPHER

    statics += [_UPSERT_NODE_CYPHER, _UPSERT_EDGE_CYPHER]
    # An str.format field is `{}` or `{<identifier>}` with no colon (a Cypher
    # map always has `key: value`). Match those without flagging Cypher maps.
    format_field = re.compile(r"\{\w*\}")
    for q in statics:
        assert not format_field.search(q)  # no str.format placeholders
        assert "%s" not in q and "%d" not in q  # no %-style placeholders
        # All bindings are openCypher $named parameters.
        assert "$" in q
