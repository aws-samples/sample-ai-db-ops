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

"""Persist Health_Reports to S3 and DynamoDB.

The S3 prefix layout matches R3.14 exactly. The DynamoDB index sits in
the `dbops-report-runs` table (R3.15) with PK `db_identifier` and SK
`report_run_id`. Tests substitute an in-memory backend.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from src.admin_ops.config.require import optional_config
from src.admin_ops.reports.generator import ReportRun

LOG = logging.getLogger(__name__)
_TABLE_NAME = "dbops-report-runs"
BUCKET_ENV = "REPORTS_BUCKET"


def _resolve_bucket(explicit: str | None) -> str:
    """Return the reports bucket, or raise if it has not been configured.

    Deliberately has **no default**. A predictable fallback name such as
    "dbops-reports" is registrable by anyone in any AWS account, so a sample
    that silently defaulted to one could be pointed at a bucket an outsider
    controls (S3 bucket squatting). The caller must name the bucket, so it is
    always an account-specific value the deployer owns.

    Precedence: explicit argument, then ``REPORTS_BUCKET``, then
    ``reports.bucket`` in ``config.yaml``.
    """
    candidate = (
        explicit
        or (os.environ.get(BUCKET_ENV) or "").strip()
        or optional_config("reports", "bucket", default=None)
    )
    if not candidate:
        raise ValueError(
            "No reports bucket configured. Pass reports_bucket=..., set "
            f"{BUCKET_ENV}, or set reports.bucket in config.yaml. There is no "
            "default because a predictable bucket name can be pre-registered "
            "by someone else."
        )
    return str(candidate)


@dataclass
class ArchivedArtifacts:
    """Result of `persist`: what was written and where."""

    s3_prefix: str
    artifact_keys: dict[str, str]
    md_sha256: str
    item: dict[str, Any]


# ── Backend abstraction ────────────────────────────────────────────────────


class _ArchiveBackend:
    def put_artifact(self, key: str, body: bytes, content_type: str) -> None:
        raise NotImplementedError

    def put_index(self, item: dict[str, Any]) -> None:
        raise NotImplementedError

    def list_runs(
        self, db_identifier: str, page_size: int = 25, exclusive_start_key: Any = None
    ) -> tuple[list[dict[str, Any]], Any]:
        raise NotImplementedError


class _InMemoryBackend(_ArchiveBackend):
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.index: list[dict[str, Any]] = []

    def put_artifact(self, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def put_index(self, item: dict[str, Any]) -> None:
        self.index.append(item)

    def list_runs(
        self, db_identifier: str, page_size: int = 25, exclusive_start_key: Any = None
    ) -> tuple[list[dict[str, Any]], Any]:
        items = [r for r in self.index if r.get("db_identifier") == db_identifier]
        items.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
        return items[:page_size], None


_backend: _ArchiveBackend | None = None
_lock = RLock()


def set_backend_for_testing(backend: _ArchiveBackend | None) -> None:
    global _backend
    with _lock:
        _backend = backend


def _get_backend() -> _ArchiveBackend:
    global _backend
    with _lock:
        if _backend is None:
            _backend = _InMemoryBackend()
        return _backend


# ── Public API ─────────────────────────────────────────────────────────────


def s3_prefix(run: ReportRun, *, reports_bucket: str) -> str:
    ts = run.generated_at.astimezone(timezone.utc)
    return (
        f"s3://{reports_bucket}/"
        f"{run.engine}/{run.db_identifier}/"
        f"{ts.strftime('%Y/%m/%d')}/{run.run_id}/"
    )


def persist(
    run: ReportRun,
    artifacts: dict[str, bytes],
    *,
    reports_bucket: str | None = None,
) -> ArchivedArtifacts:
    """Write artifacts under the run's S3 prefix and add a DynamoDB index entry.

    `artifacts` is a mapping of filename -> bytes. The Markdown body
    (`report.md`) MUST be present; PDF and CSV are optional and may be
    emitted lazily by `/api/reports/:run_id/export`.
    """
    if "report.md" not in artifacts:
        raise ValueError("artifacts must include 'report.md'")
    bucket = _resolve_bucket(reports_bucket)

    prefix = s3_prefix(run, reports_bucket=bucket)
    backend = _get_backend()
    keys: dict[str, str] = {}
    for filename, body in artifacts.items():
        key = prefix + filename
        ctype = "text/markdown" if filename.endswith(".md") else (
            "application/pdf" if filename.endswith(".pdf") else "text/csv"
        )
        backend.put_artifact(key, body, ctype)
        keys[filename] = key

    md = artifacts["report.md"]
    sha256 = hashlib.sha256(md).hexdigest()

    item = {
        "db_identifier": run.db_identifier,
        "report_run_id": run.run_id,
        "engine": run.engine,
        "cadence": run.cadence,
        "generated_at": run.generated_at.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "s3_prefix": prefix,
        "md_sha256": sha256,
        "status": run.status,
        "section_failures": list(run.section_failures),
    }
    backend.put_index(item)
    return ArchivedArtifacts(
        s3_prefix=prefix, artifact_keys=keys, md_sha256=sha256, item=item
    )


def list_runs(
    db_identifier: str,
    *,
    page_size: int = 25,
    exclusive_start_key: Any = None,
) -> tuple[list[dict[str, Any]], Any]:
    return _get_backend().list_runs(db_identifier, page_size, exclusive_start_key)
