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

"""Property P4 — Custom_Button serializer round-trip.

For every well-formed CustomButton b, parse(print(b)) == b.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from hypothesis import given, settings, strategies as st

from src.admin_ops.admin.buttons.schema import CustomButton

_LABEL = st.text(min_size=1, max_size=40)
_ICON = st.text(min_size=0, max_size=32)
_BODY = st.text(min_size=1, max_size=200)
_TARGET_SCOPE = st.text(min_size=0, max_size=128)


def _isoformat() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@settings(deadline=None, max_examples=200)
@given(
    label=_LABEL,
    icon=_ICON,
    body=_BODY,
    target_scope=_TARGET_SCOPE,
    engine=st.sampled_from(["postgresql", "mysql", "oracle", "dynamodb"]),
    body_kind=st.sampled_from(["sql", "prompt"]),
    confirmation_required=st.booleans(),
    tier_hint=st.sampled_from([1, 2, 3]),
    position=st.integers(min_value=0, max_value=10_000),
    team_id=st.one_of(st.none(), st.text(min_size=1, max_size=128)),
)
def test_p4_round_trip(
    label: str,
    icon: str,
    body: str,
    target_scope: str,
    engine: str,
    body_kind: str,
    confirmation_required: bool,
    tier_hint: int,
    position: int,
    team_id: str | None,
) -> None:
    payload = {
        "button_id": str(uuid4()),
        "owner_user_id": "alice",
        "team_id": team_id,
        "label": label,
        "icon": icon,
        "engine": engine,
        "target_scope": target_scope,
        "body_kind": body_kind,
        "body": body,
        "confirmation_required": confirmation_required,
        "tier_hint": tier_hint,
        "position": position,
        "created_at": _isoformat(),
        "updated_at": _isoformat(),
    }
    button = CustomButton.model_validate(payload)
    serialised = button.model_dump(mode="json")
    reloaded = CustomButton.model_validate(serialised)
    assert reloaded == button
