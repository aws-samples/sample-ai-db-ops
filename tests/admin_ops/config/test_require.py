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

"""Unit tests for `src.admin_ops.config.require`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from src.admin_ops.config import require as require_module
from src.admin_ops.config.require import (
    MissingConfigError,
    optional_config,
    require_config,
)


@pytest.fixture(autouse=True)
def _redirect_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point require_config at a tmp YAML for each test."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "account": {"id": "123456789012", "region": "us-east-1"},
                "ui": {"default_user_id": "dbops-user", "port": 3001},
                "empty_section": {"empty_key": None},
                "empty_string": {"key": ""},
                "empty_list": {"key": []},
                "empty_dict": {"key": {}},
                "falsy_values": {"zero": 0, "flag": False},
                "knowledge_graph": {"gating_state": "pending"},
            }
        )
    )
    monkeypatch.setenv("ADMIN_OPS_CONFIG_PATH", str(cfg))
    require_module._reset_cache()
    yield cfg
    require_module._reset_cache()


def test_returns_value_at_path() -> None:
    assert require_config("account", "id") == "123456789012"
    assert require_config("ui", "port") == 3001


def test_top_level_value() -> None:
    """A single key on the root mapping resolves."""
    # Append a top-level key for this case.
    cfg_path = Path(os.environ["ADMIN_OPS_CONFIG_PATH"])
    data = yaml.safe_load(cfg_path.read_text())
    data["top_value"] = "hello"
    cfg_path.write_text(yaml.safe_dump(data))
    require_module._reset_cache()
    assert require_config("top_value") == "hello"


def test_missing_key_raises() -> None:
    with pytest.raises(MissingConfigError) as exc:
        require_config("account", "nonexistent")
    assert exc.value.dotted_key == "account.nonexistent"


def test_empty_value_raises() -> None:
    with pytest.raises(MissingConfigError):
        require_config("empty_section", "empty_key")


def test_empty_string_raises() -> None:
    with pytest.raises(MissingConfigError) as exc:
        require_config("empty_string", "key")
    assert exc.value.dotted_key == "empty_string.key"


def test_empty_list_raises() -> None:
    with pytest.raises(MissingConfigError) as exc:
        require_config("empty_list", "key")
    assert exc.value.dotted_key == "empty_list.key"


def test_empty_dict_raises() -> None:
    with pytest.raises(MissingConfigError) as exc:
        require_config("empty_dict", "key")
    assert exc.value.dotted_key == "empty_dict.key"


def test_falsy_but_present_values_are_not_missing() -> None:
    """Numeric 0 and boolean False are legitimate configured values."""
    assert require_config("falsy_values", "zero") == 0
    assert require_config("falsy_values", "flag") is False


def test_no_keys_raises_value_error() -> None:
    with pytest.raises(ValueError):
        require_config()


def test_optional_returns_default_on_missing() -> None:
    assert optional_config("nope", default="fallback") == "fallback"
    assert optional_config("ui", "port", default=9999) == 3001


def test_missing_file_raises() -> None:
    """If the config file path is missing, raise MissingConfigError on load."""
    require_module._reset_cache()
    os.environ["ADMIN_OPS_CONFIG_PATH"] = "/nonexistent/path/config.yaml"
    with pytest.raises(MissingConfigError):
        require_config("account", "id")
