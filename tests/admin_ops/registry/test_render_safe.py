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

"""Property P3 — Template renderer SQL-injection safety.

For every TemplateSpec whose parameter `x` is type `string`, and for
every adversarial input value `v` (containing quotes, semicolons, comment
sequences), the resulting prepared-statement parameters dict contains
`v` exactly once and the rendered SQL body contains zero literal copies
of `v`.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.admin_ops.registry.render import render_template
from src.admin_ops.registry.schema import TemplateSpec

_ADVERSARIAL_TEXT = st.one_of(
    st.text(min_size=1, max_size=80),
    st.sampled_from(
        [
            "'; DROP TABLE users;--",
            "Robert');DROP TABLE Students;--",
            "1' OR '1'='1",
            "\";--",
            "/* comment */",
            "ñoño",
        ]
    ),
)


def _spec_with_string_param() -> TemplateSpec:
    return TemplateSpec.model_validate(
        {
            "template_id": "fixture_string_only",
            "engine": "postgresql",
            "tool_function_name": "fixture",
            "tier": 1,
            "description": "",
            "owner": "test",
            "parameters": [
                {"name": "needle", "type": "string", "max": 200},
            ],
            "body": "SELECT * FROM tbl WHERE col_needle = %(needle)s",
            "version": 1,
            "updated_at": "2026-05-22T00:00:00Z",
            "updated_by": "test",
        }
    )


@settings(deadline=None, max_examples=200)
@given(value=_ADVERSARIAL_TEXT)
def test_p3_injection_safe(value: str) -> None:
    spec = _spec_with_string_param()
    rendered = render_template(spec, {"needle": value})
    body = str(rendered.sql)

    # The body must remain a binding template — same shape regardless of
    # the input value. Compare against a pristine reference render.
    reference = render_template(spec, {"needle": "REFERENCE_VALUE"})
    assert str(reference.sql) == body, (
        "body is not invariant in the input value — possible injection vector"
    )

    # The bound parameters dict must hold the value exactly once.
    assert rendered.params.get("needle") == value
    occurrences = sum(1 for v in rendered.params.values() if v == value)
    assert occurrences == 1

    # And the body must NOT contain a SQL string literal with the value
    # in it (no `'...value...'` fragment outside the comment).
    quoted = f"'{value}'"
    assert quoted not in body
