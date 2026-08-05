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

"""Pydantic models for the operational query button feature.

Validates: requirement R2.1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ENGINE = Literal["postgresql", "mysql", "oracle", "dynamodb"]
BODY_KIND = Literal["prompt", "sql"]
TIER_HINT = Literal[1, 2, 3]


class CustomButton(BaseModel):
    """One operational quick-action button persisted in dbops-custom-buttons."""

    model_config = ConfigDict(extra="forbid")

    button_id: UUID
    owner_user_id: str = Field(min_length=1, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    label: str = Field(min_length=1, max_length=40)
    icon: str = Field(default="", max_length=32)
    engine: ENGINE
    target_scope: str = Field(min_length=0, max_length=128)
    body_kind: BODY_KIND
    body: str = Field(min_length=1, max_length=16000)
    confirmation_required: bool = False
    tier_hint: TIER_HINT
    position: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class CustomButtonCreate(BaseModel):
    """Subset of fields the API accepts at creation time.

    Server fills `button_id`, `owner_user_id`, `position`, `created_at`,
    and `updated_at`.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=40)
    icon: str = Field(default="", max_length=32)
    engine: ENGINE
    target_scope: str = Field(default="", max_length=128)
    body_kind: BODY_KIND
    body: str = Field(min_length=1, max_length=16000)
    confirmation_required: bool = False
    tier_hint: TIER_HINT = 1
    team_id: str | None = Field(default=None, max_length=128)


class CustomButtonPatch(BaseModel):
    """Subset of fields the PATCH endpoint accepts."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=40)
    icon: str | None = Field(default=None, max_length=32)
    target_scope: str | None = Field(default=None, max_length=128)
    body_kind: BODY_KIND | None = None
    body: str | None = Field(default=None, min_length=1, max_length=16000)
    confirmation_required: bool | None = None
    tier_hint: TIER_HINT | None = None


class ReorderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    button_id: UUID
    position: int = Field(ge=0)
