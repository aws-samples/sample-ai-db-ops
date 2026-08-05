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

"""When the admin source of truth is unreachable, callers must see the
failure as `AdminSourceUnreachable` (the middleware translates that to
HTTP 503 in R6.7).
"""

from __future__ import annotations

import pytest

from src.admin_ops.admin import role as role_mod
from src.admin_ops.admin.role import AdminSourceUnreachable
from tests.admin_ops.auth._inmemory import InMemoryBackend


def test_is_admin_propagates_backend_error() -> None:
    role_mod.set_backend_for_testing(InMemoryBackend(raise_on_call=True))
    try:
        with pytest.raises(AdminSourceUnreachable):
            role_mod.is_admin("alice")
    finally:
        role_mod.set_backend_for_testing(None)


def test_grant_propagates_backend_error() -> None:
    role_mod.set_backend_for_testing(InMemoryBackend(raise_on_call=True))
    try:
        with pytest.raises(AdminSourceUnreachable):
            role_mod.grant("alice", "test")
    finally:
        role_mod.set_backend_for_testing(None)
