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

"""Engine-specific typed parameter substitution.

Validates: R1.5, R1.6, R1.7. The renderer never builds an executable
string by concatenation — every caller-supplied value is bound through
the driver's parameter binding, with `identifier` values quoted via
engine-specific identifier rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.admin_ops.registry.schema import TemplateParameter, TemplateSpec


class TemplateRenderError(ValueError):
    """Base class for render-time errors."""


class MissingParameterError(TemplateRenderError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"missing required parameter: {name!r}")


class ParameterValidationError(TemplateRenderError):
    def __init__(self, name: str, rule: str) -> None:
        self.name = name
        self.rule = rule
        super().__init__(f"parameter {name!r} failed validation: {rule}")


class UnsupportedEngineError(TemplateRenderError):
    pass


@dataclass
class RenderedQuery:
    """A renderer output — keeps the driver-native body and bound params."""

    sql: Any  # str for most engines, psycopg2.sql.Composed for PostgreSQL
    params: dict[str, Any] = field(default_factory=dict)
    engine: str = ""

    def execute(self, conn: Any) -> list[dict[str, Any]] | int:
        """Run through `execute_with_params`, which centralises parameter
        binding and the row-or-rowcount return shape."""
        from src.admin_ops.db.execute import execute_with_params

        return execute_with_params(conn, self.sql, self.params or None)


# ─── Validation helpers ─────────────────────────────────────────────────────


def _validate(p: TemplateParameter, value: Any) -> Any:
    """Ensure `value` matches `p.type` and any min/max/enum constraints.

    Returns the (possibly-coerced) value or raises ParameterValidationError.
    """
    if p.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise ParameterValidationError(p.name, "must be int") from exc
        if p.min is not None and value < p.min:
            raise ParameterValidationError(p.name, f"min {p.min}")
        if p.max is not None and value > p.max:
            raise ParameterValidationError(p.name, f"max {p.max}")
        return value
    if p.type == "string":
        if not isinstance(value, str):
            raise ParameterValidationError(p.name, "must be str")
        if p.max is not None and len(value) > p.max:
            raise ParameterValidationError(p.name, f"max length {p.max}")
        return value
    if p.type == "identifier":
        if not isinstance(value, str) or not value:
            raise ParameterValidationError(p.name, "must be non-empty str")
        return value
    if p.type == "enum":
        if value not in (p.allowed or ()):
            raise ParameterValidationError(p.name, f"must be one of {p.allowed}")
        return value
    raise ParameterValidationError(p.name, f"unsupported type {p.type}")


# ─── Public render API ──────────────────────────────────────────────────────


def render_template(spec: TemplateSpec, params: Mapping[str, Any]) -> RenderedQuery:
    """Render a TemplateSpec into a driver-native query bundle."""
    if spec.engine == "postgresql":
        return _render_postgresql(spec, params)
    if spec.engine == "mysql":
        return _render_mysql(spec, params)
    if spec.engine == "oracle":
        return _render_oracle(spec, params)
    if spec.engine == "dynamodb":
        return _render_dynamodb(spec, params)
    raise UnsupportedEngineError(spec.engine)


def _bind(spec: TemplateSpec, params: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve every declared parameter, validate, and return the bound dict."""
    bound: dict[str, Any] = {}
    for p in spec.parameters:
        if p.name in params:
            value = params[p.name]
        elif p.default is not None:
            value = p.default
        else:
            raise MissingParameterError(p.name)
        bound[p.name] = _validate(p, value)
    return bound


def _render_postgresql(spec: TemplateSpec, params: Mapping[str, Any]) -> RenderedQuery:
    bound = _bind(spec, params)

    # Identifier params get composed via psycopg2.sql.Identifier so they
    # are quoted with PostgreSQL identifier rules. String/int values
    # remain in the bound dict and are passed through %(name)s binding.
    try:
        from psycopg2 import sql as pgsql
        has_psycopg = True
    except ImportError:  # pragma: no cover - exercised in light envs
        has_psycopg = False

    identifier_params = {
        p.name for p in spec.parameters if p.type == "identifier"
    }
    if not identifier_params or not has_psycopg:
        return RenderedQuery(sql=spec.body, params=bound, engine="postgresql")

    # Compose the body with Identifier wrappers in place of identifier
    # placeholders. We rewrite `%(name)s` for identifier params into
    # `{name}` then format with `pgsql.SQL(...).format(...)`.
    body = spec.body
    composed_kwargs = {}
    for name in identifier_params:
        body = body.replace(f"%({name})s", "{" + name + "}")
        composed_kwargs[name] = pgsql.Identifier(bound.pop(name))
    composed_sql = pgsql.SQL(body).format(**composed_kwargs)
    return RenderedQuery(sql=composed_sql, params=bound, engine="postgresql")


def _render_mysql(spec: TemplateSpec, params: Mapping[str, Any]) -> RenderedQuery:
    bound = _bind(spec, params)

    # MySQL identifier quoting uses backticks. The renderer rewrites
    # `:name` placeholders into `%(name)s` for identifier params.
    body = spec.body
    for p in spec.parameters:
        if p.type == "identifier":
            value = bound.pop(p.name)
            quoted = "`" + str(value).replace("`", "``") + "`"
            body = body.replace(f"%({p.name})s", quoted).replace(f":{p.name}", quoted)
    return RenderedQuery(sql=body, params=bound, engine="mysql")


def _render_oracle(spec: TemplateSpec, params: Mapping[str, Any]) -> RenderedQuery:
    """Oracle uses `:name` placeholders natively. Identifier params are
    inlined with double-quote wrapping; everything else is bound."""
    bound = _bind(spec, params)
    body = spec.body
    for p in spec.parameters:
        if p.type == "identifier":
            value = bound.pop(p.name)
            quoted = '"' + str(value).replace('"', '""') + '"'
            body = body.replace(f":{p.name}", quoted)
    return RenderedQuery(sql=body, params=bound, engine="oracle")


def _render_dynamodb(spec: TemplateSpec, params: Mapping[str, Any]) -> RenderedQuery:
    """DynamoDB bodies are JSON request maps. We substitute parameter
    values into the JSON tree without ever returning an executable string;
    callers use `boto3` to send the request directly.
    """
    import json

    bound = _bind(spec, params)
    try:
        body_obj = json.loads(spec.body)
    except json.JSONDecodeError as exc:
        raise TemplateRenderError(f"DynamoDB template body must be JSON: {exc}") from exc

    def _substitute(node: Any) -> Any:
        if isinstance(node, str):
            # `${name}` substitution into a JSON string node.
            for name, value in bound.items():
                node = node.replace("${" + name + "}", str(value))
            return node
        if isinstance(node, dict):
            return {k: _substitute(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_substitute(v) for v in node]
        return node

    rendered_obj = _substitute(body_obj)
    return RenderedQuery(sql=rendered_obj, params=bound, engine="dynamodb")
