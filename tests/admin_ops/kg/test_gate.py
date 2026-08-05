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

"""Unit tests for fail-closed gating resolution (R4.4, R4.5, R4.6, R10.4).

Each ``gating_state`` value plus missing/invalid → fail-closed behavior, and
``require_approved`` behavior per state. The config is redirected to a tmp YAML
per test via ``ADMIN_OPS_CONFIG_PATH`` exactly like ``test_require.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.admin_ops.config import require as require_module
from src.admin_ops.kg.gate import (
    GateUnavailable,
    gating_state,
    require_approved,
)


def _write_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(body))
    monkeypatch.setenv("ADMIN_OPS_CONFIG_PATH", str(cfg))
    require_module._reset_cache()
    return cfg


@pytest.fixture(autouse=True)
def _reset_after() -> None:
    yield
    require_module._reset_cache()


# ─── gating_state() per valid value ──────────────────────────────────────────


@pytest.mark.parametrize("state", ["pending", "approved", "not_approved"])
def test_gating_state_returns_each_valid_value(
    state: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, monkeypatch, {"knowledge_graph": {"gating_state": state}})
    assert gating_state() == state


# ─── fail-closed: missing / empty / invalid ──────────────────────────────────


def test_missing_knowledge_graph_section_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, monkeypatch, {"account": {"id": "123456789012"}})
    with pytest.raises(GateUnavailable) as exc:
        gating_state()
    assert exc.value.found is None


def test_missing_gating_key_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, monkeypatch, {"knowledge_graph": {"neptune_endpoint": ""}})
    with pytest.raises(GateUnavailable):
        gating_state()


def test_empty_gating_value_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty string is "missing" per require_config -> fail closed.
    _write_config(tmp_path, monkeypatch, {"knowledge_graph": {"gating_state": ""}})
    with pytest.raises(GateUnavailable) as exc:
        gating_state()
    assert exc.value.found is None


def test_unrecognized_gating_value_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path, monkeypatch, {"knowledge_graph": {"gating_state": "enabled"}}
    )
    with pytest.raises(GateUnavailable) as exc:
        gating_state()
    assert exc.value.found == "enabled"


def test_non_string_gating_value_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, monkeypatch, {"knowledge_graph": {"gating_state": True}})
    with pytest.raises(GateUnavailable):
        gating_state()


# ─── require_approved() per state ────────────────────────────────────────────


def test_require_approved_passes_only_when_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path, monkeypatch, {"knowledge_graph": {"gating_state": "approved"}}
    )
    # Should not raise.
    require_approved()


@pytest.mark.parametrize("state", ["pending", "not_approved"])
def test_require_approved_raises_when_not_approved(
    state: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, monkeypatch, {"knowledge_graph": {"gating_state": state}})
    with pytest.raises(GateUnavailable) as exc:
        require_approved()
    assert exc.value.found == state


def test_require_approved_fails_closed_on_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, monkeypatch, {"account": {"id": "123456789012"}})
    with pytest.raises(GateUnavailable):
        require_approved()
