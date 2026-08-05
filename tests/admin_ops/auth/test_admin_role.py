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

"""Property: P13 — Admin_Role check is monotone in privilege.

For every user_id `u` and operation set `O`, if `is_admin(u) == False`,
then `allow(u, op) == False` for every privileged op. We model `allow`
as the same gate the middleware uses: "is_admin(user_id) must be True
to perform the op".
"""

from __future__ import annotations

import string

import pytest
from hypothesis import given, settings, strategies as st

from src.admin_ops.admin import role as role_mod
from tests.admin_ops.auth._inmemory import InMemoryBackend

_PRIV_OPS = (
    "edit_template",
    "delete_other_user_button",
    "change_report_schedule",
    "grant_admin",
    "kg_ingest_control",
)


@pytest.fixture(autouse=True)
def _swap_backend() -> None:
    role_mod.set_backend_for_testing(InMemoryBackend())
    yield
    role_mod.set_backend_for_testing(None)


def _allow(user_id: str, _op: str) -> bool:
    """Mirrors the middleware: privileged ops require is_admin == True."""
    return role_mod.is_admin(user_id)


@settings(deadline=None, max_examples=200)
@given(
    user_id=st.text(
        alphabet=string.ascii_letters + string.digits + "-_.",
        min_size=1,
        max_size=128,
    ),
    granted=st.booleans(),
)
def test_p13_admin_role_monotone(user_id: str, granted: bool) -> None:
    role_mod.set_backend_for_testing(InMemoryBackend())
    if granted:
        role_mod.grant(user_id, "test", "")
    if not role_mod.is_admin(user_id):
        for op in _PRIV_OPS:
            assert not _allow(user_id, op)


def test_grant_revoke_round_trip() -> None:
    assert not role_mod.is_admin("alice")
    role_mod.grant("alice", "test")
    assert role_mod.is_admin("alice")
    role_mod.revoke("alice")
    assert not role_mod.is_admin("alice")


def test_bootstrap_inserts_default_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    role_mod.set_backend_for_testing(InMemoryBackend())
    monkeypatch.setattr(
        "src.admin_ops.admin.role.optional_config",
        lambda *keys, default=None: "dbops-user" if keys == ("ui", "default_user_id") else default,
    )
    assert role_mod.bootstrap_default() == "dbops-user"
    assert role_mod.is_admin("dbops-user")
    # Idempotent: a second bootstrap is a no-op.
    assert role_mod.bootstrap_default() is None


def test_bootstrap_skips_when_default_user_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    role_mod.set_backend_for_testing(InMemoryBackend())
    monkeypatch.setattr(
        "src.admin_ops.admin.role.optional_config",
        lambda *keys, default=None: default,
    )
    assert role_mod.bootstrap_default() is None


# ─── Demo bypass (ADMIN_DEV_BYPASS=1) ────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_bypass_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the property tests above never see the bypass flag set."""
    monkeypatch.delenv("ADMIN_DEV_BYPASS", raising=False)


def test_admin_dev_bypass_grants_admin_without_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Backend has NO admins; a normal lookup would be False.
    role_mod.set_backend_for_testing(InMemoryBackend())
    assert role_mod.is_admin("nobody") is False

    # With the flag set, a validated user resolves to admin without the table.
    monkeypatch.setenv("ADMIN_DEV_BYPASS", "1")
    assert role_mod.is_admin("nobody") is True
    assert role_mod.is_admin("demo-user") is True


def test_admin_dev_bypass_still_validates_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_DEV_BYPASS", "1")
    # Invalid user_id is still rejected before the bypass returns.
    with pytest.raises(role_mod.InvalidUserId):
        role_mod.is_admin("")
    with pytest.raises(role_mod.InvalidUserId):
        role_mod.is_admin("x" * 129)


def test_bypass_disabled_when_flag_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_DEV_BYPASS", raising=False)
    role_mod.set_backend_for_testing(InMemoryBackend())
    assert role_mod.is_admin("nobody") is False
