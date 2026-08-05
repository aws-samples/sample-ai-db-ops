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

"""Pydantic models for the admin-ops-console template registry.

A `TemplateSpec` is one entry in the registry. The on-disk format is a
YAML or JSON file under `src/admin_ops/registry/templates/<engine>/<id>.yaml`.

Validates: requirement R1.1 (every field constraint comes from the
acceptance criteria).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ENGINE = Literal["postgresql", "mysql", "oracle", "dynamodb"]
PARAM_TYPE = Literal["int", "string", "identifier", "enum"]
TIER = Literal[1, 2, 3]

_TEMPLATE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PYTHON_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Match `%(name)s` (psycopg2-style) and `:name` (oracledb-style) and `$name`.
# We treat any of these as a placeholder that must appear in `parameters`.
_PLACEHOLDER_RE = re.compile(
    r"%\((?P<n1>[a-zA-Z_][a-zA-Z0-9_]*)\)s|"  # psycopg2 / pymysql style
    r"(?<!:):(?P<n2>[a-zA-Z_][a-zA-Z0-9_]*)|"  # oracledb :name (not ::cast)
    r"\$\{(?P<n3>[a-zA-Z_][a-zA-Z0-9_]*)\}"   # ${name} JSON-string substitution
)


class TemplateLoadError(ValueError):
    """Raised when a Template_Spec fails parsing or schema validation."""


class TemplateParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    type: PARAM_TYPE
    default: Any | None = None
    min: int | None = None
    max: int | None = None
    allowed: list[str] | None = None  # required when type == "enum"

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not _PYTHON_IDENT_RE.match(v):
            raise ValueError(f"parameter name {v!r} is not a valid identifier")
        return v

    @model_validator(mode="after")
    def _check_enum(self) -> "TemplateParameter":
        if self.type == "enum":
            if not self.allowed:
                raise ValueError("enum parameters must declare a non-empty `allowed` list")
            if not (1 <= len(self.allowed) <= 32):
                raise ValueError("enum `allowed` length must be 1..32")
        return self


class TemplateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=64)
    engine: ENGINE
    tool_function_name: str = Field(min_length=1, max_length=64)
    tier: TIER
    description: str = Field(default="", max_length=1000)
    owner: str = Field(min_length=1, max_length=128)
    parameters: list[TemplateParameter] = Field(default_factory=list, max_length=32)
    body: str = Field(min_length=1, max_length=16000)
    version: int = Field(ge=1)
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=128)

    @field_validator("template_id")
    @classmethod
    def _check_template_id(cls, v: str) -> str:
        if not _TEMPLATE_ID_RE.match(v):
            raise ValueError(
                f"template_id {v!r} must match {_TEMPLATE_ID_RE.pattern}"
            )
        return v

    @field_validator("tool_function_name")
    @classmethod
    def _check_tool_function_name(cls, v: str) -> str:
        if not _PYTHON_IDENT_RE.match(v):
            raise ValueError(f"tool_function_name {v!r} is not a valid Python identifier")
        return v

    @model_validator(mode="after")
    def _placeholders_must_be_declared(self) -> "TemplateSpec":
        declared = {p.name for p in self.parameters}
        # Strip out comment lines so commented-out placeholders don't trip
        # the check; this is conservative.
        scrubbed = re.sub(r"--.*?$", "", self.body, flags=re.MULTILINE)
        scrubbed = re.sub(r"/\*.*?\*/", "", scrubbed, flags=re.DOTALL)
        used: set[str] = set()
        for m in _PLACEHOLDER_RE.finditer(scrubbed):
            name = m.group("n1") or m.group("n2") or m.group("n3")
            if name:
                used.add(name)
        missing = used - declared
        if missing:
            raise ValueError(
                f"body references undeclared placeholder(s): {sorted(missing)}"
            )
        return self

    @classmethod
    def parse_file(cls, path: Any) -> "TemplateSpec":
        """Load YAML or JSON, parse into a TemplateSpec, raise on error."""
        import yaml

        from pathlib import Path as _P

        p = _P(path)
        try:
            text = p.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
        except (OSError, yaml.YAMLError) as exc:
            raise TemplateLoadError(f"{p}: {exc}") from exc
        if not isinstance(data, dict):
            raise TemplateLoadError(f"{p}: top-level must be a mapping")
        try:
            return cls.model_validate(data)
        except Exception as exc:
            raise TemplateLoadError(f"{p}: {exc}") from exc
