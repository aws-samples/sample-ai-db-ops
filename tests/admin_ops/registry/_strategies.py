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

"""Hypothesis strategies shared across the registry property tests."""

from __future__ import annotations

import string
from datetime import datetime, timezone
from typing import Any

from hypothesis import strategies as st

_TEMPLATE_ID_ALPHA = string.ascii_lowercase + string.digits + "_"
_PARAM_NAME_ALPHA = string.ascii_letters + string.digits + "_"


def template_id_st() -> st.SearchStrategy[str]:
    return st.from_regex(r"^[a-z][a-z0-9_]{0,40}$", fullmatch=True)


def python_ident_st() -> st.SearchStrategy[str]:
    return st.from_regex(r"^[a-z][a-z0-9_]{0,40}$", fullmatch=True)


def param_name_st() -> st.SearchStrategy[str]:
    return st.from_regex(r"^[a-z][a-z0-9_]{0,30}$", fullmatch=True)


def _int_param(name: str) -> dict[str, Any]:
    return {"name": name, "type": "int", "default": 1, "min": 1, "max": 100}


def _str_param(name: str) -> dict[str, Any]:
    return {"name": name, "type": "string", "default": "x", "max": 100}


def _ident_param(name: str) -> dict[str, Any]:
    return {"name": name, "type": "identifier", "default": "tbl"}


def _enum_param(name: str) -> dict[str, Any]:
    return {"name": name, "type": "enum", "allowed": ["a", "b", "c"], "default": "a"}


def template_spec_dict_st() -> st.SearchStrategy[dict[str, Any]]:
    """Generate dicts that round-trip through TemplateSpec validation.

    We use a small parameter-set generator and ensure every placeholder
    in the body is declared in the parameters list.
    """
    @st.composite
    def _gen(draw: st.DrawFn) -> dict[str, Any]:
        # 0-3 distinct parameter names
        names = draw(
            st.lists(
                param_name_st(),
                min_size=0,
                max_size=3,
                unique=True,
            )
        )
        param_kinds = ["int", "string", "identifier", "enum"]
        params: list[dict[str, Any]] = []
        for n in names:
            kind = draw(st.sampled_from(param_kinds))
            if kind == "int":
                params.append(_int_param(n))
            elif kind == "string":
                params.append(_str_param(n))
            elif kind == "identifier":
                params.append(_ident_param(n))
            else:
                params.append(_enum_param(n))

        # Body references every declared placeholder once. This is test-fixture
        # data (a generated template body) that is never executed against a DB.
        clauses = " AND ".join(f"col_{n} = %({n})s" for n in names) or "1=1"
        body = f"SELECT 1 FROM tbl WHERE {clauses}"  # nosec B608

        return {
            "template_id": draw(template_id_st()),
            "engine": draw(st.sampled_from(["postgresql", "mysql", "oracle"])),
            "tool_function_name": draw(python_ident_st()),
            "tier": draw(st.sampled_from([1, 2, 3])),
            "description": "",
            "owner": "test",
            "parameters": params,
            "body": body,
            "version": draw(st.integers(min_value=1, max_value=999)),
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            "updated_by": "test",
        }

    return _gen()
