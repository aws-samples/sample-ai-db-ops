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

"""Missing owner_user_id is rejected at the store layer (R2.3).

The middleware (R6.8) returns 401 before reaching the store; this test
guards the second line of defence.
"""

from __future__ import annotations

import pytest

from src.admin_ops.admin.buttons import store as store_mod
from src.admin_ops.admin.buttons.schema import CustomButtonCreate
from tests.admin_ops.buttons._inmemory import InMemoryButtonBackend


def test_create_rejects_empty_owner() -> None:
    store_mod.set_backend_for_testing(InMemoryButtonBackend())
    with pytest.raises(ValueError):
        store_mod.create_button(
            "",
            CustomButtonCreate(
                label="x", engine="postgresql", body_kind="sql", body="SELECT 1", tier_hint=1
            ),
        )


def test_list_rejects_empty_owner() -> None:
    store_mod.set_backend_for_testing(InMemoryButtonBackend())
    with pytest.raises(ValueError):
        store_mod.list_buttons("")
