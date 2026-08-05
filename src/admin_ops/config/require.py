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

"""Fail-closed configuration access for the admin-ops-console.

Loads `config.yaml` once per process (cached), provides `require_config`
which raises `MissingConfigError` for missing or empty values, and
`optional_config` which returns a caller-supplied default. The location
of `config.yaml` can be overridden by setting `ADMIN_OPS_CONFIG_PATH`
(useful in tests).

Validates: requirement R7.8.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any

import yaml


class MissingConfigError(RuntimeError):
    """Raised when a required configuration key is missing or empty."""

    def __init__(self, dotted_key: str, reason: str | None = None) -> None:
        self.dotted_key = dotted_key
        self.reason = reason
        message = f"Missing required configuration key: {dotted_key!r}"
        if reason:
            message += f" ({reason})"
        super().__init__(message)


_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config.yaml"
_cache: dict[str, Any] | None = None
_cache_lock = Lock()


def _reset_cache() -> None:
    """Drop the in-memory cache. Called by tests."""
    global _cache
    with _cache_lock:
        _cache = None


def _config_path() -> Path:
    override = os.environ.get("ADMIN_OPS_CONFIG_PATH")
    return Path(override) if override else _DEFAULT_PATH


def _is_empty(value: Any) -> bool:
    """Return True for "empty" config values: None, empty string, or empty
    collection (list/dict/tuple/set).

    Numeric ``0`` and boolean ``False`` are intentionally NOT empty — they are
    legitimate configured values.
    """
    if value is None:
        return True
    if isinstance(value, (str, list, dict, tuple, set)):
        return len(value) == 0
    return False


def _load() -> dict[str, Any]:
    global _cache
    with _cache_lock:
        if _cache is not None:
            return _cache
        path = _config_path()
        if not path.exists():
            raise MissingConfigError(
                str(path), reason="config.yaml not found at configured path"
            )
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise MissingConfigError(str(path), reason=f"YAML parse error: {exc}") from exc
        if not isinstance(data, dict):
            raise MissingConfigError(
                str(path), reason="config.yaml top level is not a mapping"
            )
        _cache = data
        return _cache


def require_config(*keys: str) -> Any:
    """Return the value at the dotted path, or raise `MissingConfigError`.

    A value is "missing" if any intermediate key is absent, the leaf value
    is `None`, or the leaf value is an empty string.
    """
    if not keys:
        raise ValueError("require_config requires at least one key")
    cfg = _load()
    cur: Any = cfg
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            raise MissingConfigError(".".join(keys))
        cur = cur[k]
    if _is_empty(cur):
        raise MissingConfigError(".".join(keys), reason="value is empty")
    return cur


def optional_config(*keys: str, default: Any = None) -> Any:
    """Return the value at the dotted path, or `default` if missing or empty."""
    try:
        return require_config(*keys)
    except MissingConfigError:
        return default
