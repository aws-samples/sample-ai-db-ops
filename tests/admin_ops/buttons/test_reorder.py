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

"""Property P6 — Custom_Button reorder is a permutation.

For every list of CustomButtons L and every reorder operation r, the
multiset of button_id values in reorder(L, r) equals the multiset in L.
Reordering preserves membership.
"""

from __future__ import annotations

import string
from datetime import datetime, timezone
from typing import List
from uuid import uuid4

from hypothesis import HealthCheck, given, settings, strategies as st

from src.admin_ops.admin.buttons import store as store_mod
from src.admin_ops.admin.buttons.schema import (
    CustomButton,
    CustomButtonCreate,
    ReorderEntry,
)
from tests.admin_ops.buttons._inmemory import InMemoryButtonBackend


def _seed(n: int, owner: str = "alice") -> List[CustomButton]:
    store_mod.set_backend_for_testing(InMemoryButtonBackend())
    out: list[CustomButton] = []
    for i in range(n):
        b = store_mod.create_button(
            owner,
            CustomButtonCreate(
                label=f"L{i}",
                engine="postgresql",
                body_kind="sql",
                body="SELECT 1",
                tier_hint=1,
            ),
            next_position=i,
        )
        out.append(b)
    return out


@settings(deadline=None, max_examples=80, suppress_health_check=[HealthCheck.too_slow])
@given(n=st.integers(min_value=0, max_value=8), seed=st.integers())
def test_p6_reorder_is_permutation(n: int, seed: int) -> None:
    import random

    buttons = _seed(n)
    rng = random.Random(seed)
    new_positions = list(range(n))
    rng.shuffle(new_positions)
    updates = [
        ReorderEntry(button_id=b.button_id, position=new_positions[i])
        for i, b in enumerate(buttons)
    ]
    store_mod.reorder_buttons("alice", updates)
    after = store_mod.list_buttons("alice")
    assert {b.button_id for b in after} == {b.button_id for b in buttons}


def test_reorder_atomicity_rolls_back_on_invalid_button_id() -> None:
    buttons = _seed(3)
    valid = ReorderEntry(button_id=buttons[0].button_id, position=99)
    invalid = ReorderEntry(button_id=uuid4(), position=42)
    try:
        store_mod.reorder_buttons("alice", [valid, invalid])
    except KeyError:
        # All-or-nothing: the valid update must NOT have applied.
        after = store_mod.list_buttons("alice")
        assert {b.position for b in after} == {0, 1, 2}
        return
    assert False, "expected ButtonNotFound"
