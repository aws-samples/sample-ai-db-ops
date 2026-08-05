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

"""Property P1 — Template registry parser/printer round-trip.

For every valid TemplateSpec, `parse(print(parse(file))) == parse(file)`.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings

from src.admin_ops.registry.schema import TemplateSpec
from src.admin_ops.registry.serialize import dump_one, load_one
from tests.admin_ops.registry._strategies import template_spec_dict_st


@settings(deadline=None, max_examples=150, suppress_health_check=[HealthCheck.too_slow])
@given(spec_dict=template_spec_dict_st())
def test_p1_round_trip(spec_dict: dict) -> None:
    spec = TemplateSpec.model_validate(spec_dict)
    text = dump_one(spec)
    reloaded = load_one(text)
    text2 = dump_one(reloaded)
    reloaded2 = load_one(text2)
    assert reloaded == reloaded2
    assert reloaded.template_id == spec.template_id
    assert reloaded.engine == spec.engine
    assert reloaded.body == spec.body
