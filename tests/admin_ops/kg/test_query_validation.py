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

"""Property S3 (R5.2, R5.3) — query parameter joint precondition.

For any (hops, days, node_id): ``connected`` is authorized IFF hops in 1..3 AND
days in 1..365 AND node_id exists in the backend. Otherwise it raises
InvalidQuery naming an offending parameter and performs NO traversal.

The model enforces the ranges on a normally-constructed TraversalParams, so we
use ``model_construct`` to bypass validation and feed out-of-range values to the
explicit joint check inside ``connected``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

from hypothesis import given, settings, strategies as st

from src.admin_ops.kg import store as store_mod
from src.admin_ops.kg.ingest import map_change_event
from src.admin_ops.kg.query import InvalidQuery, TraversalParams, connected
from src.admin_ops.kg.store import InMemoryGraphBackend
from tests.admin_ops.kg._inmemory import ACCOUNT_KEY, change_events

_KNOWN_FOCUS = "ChangeEvent:focus-known"
_UNKNOWN_FOCUS = "ChangeEvent:does-not-exist"


def _seed_one(events) -> InMemoryGraphBackend:
    """A backend with the generated events plus one guaranteed known node."""
    backend = InMemoryGraphBackend()
    for e in events:
        backend.upsert(map_change_event(e, account_key=ACCOUNT_KEY))
    # Guarantee a known focus node exists regardless of generated events.
    from src.admin_ops.kg.model import GraphNode

    backend._nodes[_KNOWN_FOCUS] = GraphNode(
        node_id=_KNOWN_FOCUS,
        type="ChangeEvent",
        label="focus",
        props={"contributing_ts": datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat()},
    )
    return backend


# Feature: dba-knowledge-graph, Property S3: query parameter joint precondition
@settings(deadline=None, max_examples=200)
@given(
    events=st.lists(change_events(), max_size=8),
    hops=st.integers(min_value=-2, max_value=6),
    days=st.integers(min_value=-5, max_value=400),
    focus_known=st.booleans(),
)
def test_s3_joint_precondition(events, hops: int, days: int, focus_known: bool) -> None:
    backend = _seed_one(events)
    store_mod.set_backend_for_testing(backend)
    try:
        focus = _KNOWN_FOCUS if focus_known else _UNKNOWN_FOCUS
        params = TraversalParams.model_construct(
            focus_node_id=focus, hops=hops, days=days
        )

        hops_ok = 1 <= hops <= 3
        days_ok = 1 <= days <= 365
        focus_ok = focus_known
        all_ok = hops_ok and days_ok and focus_ok

        # Spy on the traversal so we can prove none happens on failure.
        with mock.patch.object(
            backend, "neighbors", wraps=backend.neighbors
        ) as spy:
            if all_ok:
                result = connected(params)
                assert result.focus == focus
                assert spy.call_count == 1
            else:
                try:
                    connected(params)
                except InvalidQuery as exc:
                    # The named parameter must be one that is actually invalid.
                    invalid_params = set()
                    if not hops_ok:
                        invalid_params.add("hops")
                    if not days_ok:
                        invalid_params.add("days")
                    if not focus_ok:
                        invalid_params.add("focus_node_id")
                    assert exc.parameter in invalid_params
                else:
                    raise AssertionError("expected InvalidQuery")
                # No traversal performed on failure.
                assert spy.call_count == 0
    finally:
        store_mod.set_backend_for_testing(None)


# Feature: dba-knowledge-graph, Property S3: check order is hops, days, focus
@settings(deadline=None, max_examples=100)
@given(
    hops=st.integers(min_value=-2, max_value=6),
    days=st.integers(min_value=-5, max_value=400),
)
def test_s3_offending_parameter_precedence(hops: int, days: int) -> None:
    # With an unknown focus and possibly-bad hops/days, the FIRST failing check
    # (hops, then days, then focus_node_id) determines the named parameter.
    backend = InMemoryGraphBackend()
    store_mod.set_backend_for_testing(backend)
    try:
        params = TraversalParams.model_construct(
            focus_node_id=_UNKNOWN_FOCUS, hops=hops, days=days
        )
        hops_ok = 1 <= hops <= 3
        days_ok = 1 <= days <= 365
        try:
            connected(params)
        except InvalidQuery as exc:
            if not hops_ok:
                assert exc.parameter == "hops"
            elif not days_ok:
                assert exc.parameter == "days"
            else:
                assert exc.parameter == "focus_node_id"
        else:
            raise AssertionError("expected InvalidQuery for unknown focus")
    finally:
        store_mod.set_backend_for_testing(None)
