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

"""Validation tests for CustomButton fields (R2.5, R2.6)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.admin_ops.admin.buttons.schema import CustomButtonCreate


def _base() -> dict:
    return {
        "label": "Slow Queries",
        "engine": "postgresql",
        "body_kind": "sql",
        "body": "SELECT 1",
        "tier_hint": 1,
    }


def test_label_required() -> None:
    with pytest.raises(ValidationError):
        CustomButtonCreate.model_validate({**_base(), "label": ""})


def test_label_too_long() -> None:
    with pytest.raises(ValidationError):
        CustomButtonCreate.model_validate({**_base(), "label": "x" * 41})


def test_engine_enum() -> None:
    with pytest.raises(ValidationError):
        CustomButtonCreate.model_validate({**_base(), "engine": "redis"})


def test_body_kind_enum() -> None:
    with pytest.raises(ValidationError):
        CustomButtonCreate.model_validate({**_base(), "body_kind": "shell"})


def test_body_required() -> None:
    with pytest.raises(ValidationError):
        CustomButtonCreate.model_validate({**_base(), "body": ""})


def test_tier_hint_in_range() -> None:
    with pytest.raises(ValidationError):
        CustomButtonCreate.model_validate({**_base(), "tier_hint": 7})


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        CustomButtonCreate.model_validate({**_base(), "rogue": "value"})
