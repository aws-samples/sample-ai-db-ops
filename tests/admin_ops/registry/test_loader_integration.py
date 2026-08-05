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

"""Loader integration: real fixture under templates/postgresql loads cleanly."""

from __future__ import annotations

from src.admin_ops.registry.loader import TemplateRegistry


def test_load_postgresql_fixture() -> None:
    reg = TemplateRegistry()
    reg.load()
    spec = reg.get("pg_get_slow_queries")
    assert spec is not None
    assert spec.engine == "postgresql"
    assert spec.tier == 1
    assert reg.failures() == []


def test_render_postgresql_fixture_with_default() -> None:
    reg = TemplateRegistry()
    reg.load()
    rendered = reg.render("pg_get_slow_queries", {})
    body = str(rendered.sql)
    assert "%(top_n)s" in body
    assert rendered.params == {"top_n": 10}
    assert rendered.engine == "postgresql"


def test_render_postgresql_fixture_with_override() -> None:
    reg = TemplateRegistry()
    reg.load()
    rendered = reg.render("pg_get_slow_queries", {"top_n": 25})
    assert rendered.params == {"top_n": 25}


def test_render_postgresql_validation_caps_top_n() -> None:
    reg = TemplateRegistry()
    reg.load()
    try:
        reg.render("pg_get_slow_queries", {"top_n": 9999})
    except Exception as e:
        assert "max" in str(e).lower()
        return
    assert False, "expected ParameterValidationError"
