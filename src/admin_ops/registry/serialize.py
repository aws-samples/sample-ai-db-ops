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

"""Deterministic pretty printer for TemplateSpec lists.

Output is sorted ascending by `template_id` and emits fields in a fixed
order. Round-trip property: `parse(print(parse(file))) == parse(file)`
(P1).
"""

from __future__ import annotations

from typing import Any

import yaml

from src.admin_ops.registry.schema import TemplateSpec

_FIELD_ORDER: tuple[str, ...] = (
    "template_id",
    "engine",
    "tool_function_name",
    "tier",
    "description",
    "owner",
    "parameters",
    "body",
    "version",
    "updated_at",
    "updated_by",
)


def _spec_to_ordered_dict(spec: TemplateSpec) -> dict[str, Any]:
    raw = spec.model_dump(mode="json")
    return {k: raw[k] for k in _FIELD_ORDER if k in raw}


class _LiteralStr(str):
    """str subclass that yaml dumps as a literal block scalar."""


def _literal_str_representer(dumper: yaml.SafeDumper, data: _LiteralStr) -> Any:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


yaml.SafeDumper.add_representer(_LiteralStr, _literal_str_representer)


def _wrap_body(d: dict[str, Any]) -> dict[str, Any]:
    """Mark the `body` field as a YAML literal block for readability.

    Returns a copy; never mutates the input.
    """
    out = dict(d)
    if "body" in out and isinstance(out["body"], str):
        out["body"] = _LiteralStr(out["body"])
    return out


def dumps(specs: list[TemplateSpec]) -> str:
    ordered = [
        _wrap_body(_spec_to_ordered_dict(s))
        for s in sorted(specs, key=lambda x: x.template_id)
    ]
    return yaml.safe_dump_all(
        ordered,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def dump_one(spec: TemplateSpec) -> str:
    return yaml.safe_dump(
        _wrap_body(_spec_to_ordered_dict(spec)),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def loads(text: str) -> list[TemplateSpec]:
    docs = list(yaml.safe_load_all(text))
    return [TemplateSpec.model_validate(d) for d in docs if d is not None]


def load_one(text: str) -> TemplateSpec:
    return TemplateSpec.model_validate(yaml.safe_load(text))
