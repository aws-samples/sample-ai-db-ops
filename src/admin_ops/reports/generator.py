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

"""Health report generator.

Composes deterministic Markdown from a typed input bundle.

Tier-1-only enforcement is the responsibility of the caller — the
generator never executes Tier 2 or Tier 3 tools (R3.4). When a section
fails to render, the generator wraps the failure in a `Section Failed`
block and the report's run status becomes `partial` (R3.18).

Validates: R3.1, R3.2, R3.4, R3.5, R3.18, R3.19. Property P7.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping
from uuid import uuid4

from src.admin_ops.errors import safe_error
from src.admin_ops.reports.format import utc_isoformat
from src.admin_ops.reports.sections import SECTIONS

LOG = logging.getLogger(__name__)


RunStatus = Literal["success", "partial", "failed"]


@dataclass
class ReportRun:
    db_identifier: str
    engine: str
    cadence: str
    run_id: str
    generated_at: datetime
    status: RunStatus = "success"
    section_failures: list[str] = field(default_factory=list)


def render_report(
    *,
    bundle: Mapping[str, Any],
    db_identifier: str,
    engine: str,
    cadence: str,
    run_id: str,
    generated_at: datetime,
) -> tuple[str, ReportRun]:
    """Render a full Health_Report Markdown body.

    `bundle` is a typed dict with one key per section
    (`top_slow_queries`, `blocking_incidents`, `unused_indexes`,
    `capacity_headroom`, `vacuum_undo_status`, `tier3_ops`, `summary`).
    Each renderer expects its own shape (see `sections/*.py`).

    The function never raises — section-level failures land in a
    `Section Failed` block instead. Determinism: header values are
    pinned (`run_id`, `generated_at`); float formatting goes through
    `fnum`; dict iteration uses sorted keys via the section renderers.
    """
    run = ReportRun(
        db_identifier=db_identifier,
        engine=engine,
        cadence=cadence,
        run_id=run_id,
        generated_at=generated_at,
    )

    parts: list[str] = []
    parts.append(f"# Database Health Report — {db_identifier}")
    parts.append("")
    parts.append(f"- **Engine**: {engine}")
    parts.append(f"- **Cadence**: {cadence}")
    parts.append(f"- **Run ID**: {run_id}")
    parts.append(f"- **Generated at (UTC)**: {utc_isoformat(generated_at)}")
    parts.append("")

    for title, render_fn in SECTIONS:
        parts.append(f"## {title}")
        parts.append("")
        try:
            section_text = render_fn(bundle)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("section %s failed: %s", title, exc)
            run.section_failures.append(title)
            # The rendered report is an artifact that may be exported and shared,
            # so it carries the failure type only — never the exception message,
            # which can contain rows from the bundle being rendered.
            section_text = (
                f"> **Section Failed.** "
                f"`{title}` could not be rendered: `{safe_error(exc)}`."
            )
        parts.append(section_text)
        parts.append("")

    if run.section_failures:
        run.status = "partial"

    body = "\n".join(parts).rstrip() + "\n"
    return body, run


def make_run_id(*, prefix: str = "run") -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
