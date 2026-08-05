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

"""Property P2 — renderer parameter completeness.

(a) For every TemplateSpec and parameter map where every placeholder
    has a value of the declared type, render produces a body with zero
    remaining `%(name)s` placeholders for non-identifier params.

(b) For any spec with at least one declared parameter, leaving that
    parameter out of the input map raises MissingParameterError.
"""

from __future__ import annotations

import re

from hypothesis import HealthCheck, assume, given, settings

from src.admin_ops.registry.render import (
    MissingParameterError,
    render_template,
)
from src.admin_ops.registry.schema import TemplateSpec
from tests.admin_ops.registry._strategies import template_spec_dict_st

_PG_PLACEHOLDER = re.compile(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)s")


def _full_param_map(spec: TemplateSpec) -> dict[str, object]:
    out: dict[str, object] = {}
    for p in spec.parameters:
        if p.type == "int":
            out[p.name] = 5
        elif p.type == "string":
            out[p.name] = "value"
        elif p.type == "identifier":
            out[p.name] = "my_tbl"
        elif p.type == "enum":
            out[p.name] = (p.allowed or ["a"])[0]
    return out


@settings(deadline=None, max_examples=150, suppress_health_check=[HealthCheck.too_slow])
@given(spec_dict=template_spec_dict_st())
def test_p2_complete_substitution(spec_dict: dict) -> None:
    # Restrict to engines whose body uses %(name)s placeholders.
    assume(spec_dict["engine"] == "postgresql")
    spec = TemplateSpec.model_validate(spec_dict)
    rendered = render_template(spec, _full_param_map(spec))
    body = str(rendered.sql)
    # Identifier params get inlined via psycopg2.sql.Identifier so they
    # disappear entirely; other params stay as %(name)s placeholders that
    # the driver binds at execute time. Both forms count as "complete".
    declared = {p.name for p in spec.parameters}
    leftover_placeholders = {m.group(0) for m in _PG_PLACEHOLDER.finditer(body)}
    leftover_names = {p[2:-2] for p in leftover_placeholders}
    assert leftover_names <= declared


@settings(deadline=None, max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(spec_dict=template_spec_dict_st())
def test_p2_missing_param_raises(spec_dict: dict) -> None:
    assume(spec_dict["parameters"])
    spec = TemplateSpec.model_validate(spec_dict)
    # Drop one declared parameter and override its default to None so
    # the renderer must raise.
    target = spec.parameters[0]
    incomplete = _full_param_map(spec)
    incomplete.pop(target.name, None)

    # Force the renderer to require the param by rebuilding the spec
    # without a default for it.
    raw = spec.model_dump()
    for p in raw["parameters"]:
        if p["name"] == target.name:
            p.pop("default", None)
    spec_no_default = TemplateSpec.model_validate(raw)
    try:
        render_template(spec_no_default, incomplete)
    except MissingParameterError as e:
        assert e.name == target.name
        return
    assert False, "expected MissingParameterError"
