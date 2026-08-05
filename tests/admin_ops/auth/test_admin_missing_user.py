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

"""Missing or invalid user_id surfaces as InvalidUserId.

The middleware translates this into HTTP 401 per R6.8.
"""

from __future__ import annotations

import pytest

from src.admin_ops.admin import role as role_mod
from src.admin_ops.admin.role import InvalidUserId
from tests.admin_ops.auth._inmemory import InMemoryBackend


@pytest.fixture(autouse=True)
def _swap_backend() -> None:
    role_mod.set_backend_for_testing(InMemoryBackend())
    yield
    role_mod.set_backend_for_testing(None)


def test_none_user_id() -> None:
    with pytest.raises(InvalidUserId):
        role_mod.is_admin(None)


def test_empty_user_id() -> None:
    with pytest.raises(InvalidUserId):
        role_mod.is_admin("")


def test_too_long_user_id() -> None:
    with pytest.raises(InvalidUserId):
        role_mod.is_admin("x" * 129)


def test_non_string_user_id() -> None:
    with pytest.raises(InvalidUserId):
        role_mod.is_admin(12345)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_user_id", [None, "", "x" * 129])
def test_invalid_user_id_does_not_touch_store(bad_user_id: object) -> None:
    """R6.8: validation precedes any store access.

    A backend wired to raise on *any* call stands in for the admin store.
    If validation ran first (as required), ``InvalidUserId`` surfaces and the
    backend is never consulted; if the store were touched we would instead see
    ``AdminSourceUnreachable``. Asserting ``InvalidUserId`` proves the store is
    left untouched for missing/empty/oversized user_ids.
    """
    role_mod.set_backend_for_testing(InMemoryBackend(raise_on_call=True))
    with pytest.raises(InvalidUserId):
        role_mod.is_admin(bad_user_id)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_user_id", [None, "", "x" * 129])
def test_invalid_user_id_does_not_mutate_via_grant(bad_user_id: object) -> None:
    """R6.8: a mutating op (grant) also rejects before any store write."""
    backend = InMemoryBackend(raise_on_call=True)
    role_mod.set_backend_for_testing(backend)
    with pytest.raises(InvalidUserId):
        role_mod.grant(bad_user_id, "actor")  # type: ignore[arg-type]
    # Switch to a non-raising backend to confirm no record leaked through.
    role_mod.set_backend_for_testing(InMemoryBackend())
    assert role_mod.list_admins() == []
