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

"""R3.18 — section failure produces Section Failed block, run is partial."""

from __future__ import annotations

from datetime import datetime, timezone

from src.admin_ops.reports import generator
from src.admin_ops.reports.sections import SECTIONS


def test_failing_section_yields_partial_run(monkeypatch):
    # Replace one section's renderer with one that raises.
    new_sections = list(SECTIONS)
    new_sections[1] = (
        new_sections[1][0],
        lambda bundle: (_ for _ in ()).throw(RuntimeError("simulated failure")),
    )
    monkeypatch.setattr(
        "src.admin_ops.reports.generator.SECTIONS", new_sections
    )
    body, run = generator.render_report(
        bundle={},
        db_identifier="db",
        engine="postgresql",
        cadence="manual",
        run_id="run-x",
        generated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    assert run.status == "partial"
    assert run.section_failures == ["Top Slow Queries"]
    assert "Section Failed" in body
    assert "Top Slow Queries" in body


def test_clean_run_is_success():
    body, run = generator.render_report(
        bundle={},
        db_identifier="db",
        engine="postgresql",
        cadence="manual",
        run_id="run-y",
        generated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    assert run.status == "success"
    assert run.section_failures == []
    assert "Section Failed" not in body
