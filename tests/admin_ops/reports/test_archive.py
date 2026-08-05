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

"""Round-trip the archive: persist a run, read the index back."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.admin_ops.config import require as require_mod
from src.admin_ops.reports import archive as archive_mod
from src.admin_ops.reports.archive import _InMemoryBackend
from src.admin_ops.reports.generator import ReportRun

# Deliberately not a plausible production bucket name. A realistic name in a
# fixture invites someone to copy it into real code, where a predictable name
# is registrable by anyone (S3 bucket squatting).
_TEST_BUCKET = "example-invalid-test-bucket-do-not-create"


def test_persist_and_list():
    backend = _InMemoryBackend()
    archive_mod.set_backend_for_testing(backend)
    try:
        run = ReportRun(
            db_identifier="db-1",
            engine="postgresql",
            cadence="weekly",
            run_id="run-aaa",
            generated_at=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
        )
        result = archive_mod.persist(
            run,
            {
                "report.md": b"# Test\n\nbody",
                "report.csv": b"col\nvalue\n",
            },
            reports_bucket=_TEST_BUCKET,
        )
        assert result.s3_prefix.startswith(
            f"s3://{_TEST_BUCKET}/postgresql/db-1/2026/05/22/run-aaa/"
        )
        assert "report.md" in result.artifact_keys
        assert "report.csv" in result.artifact_keys
        assert len(result.md_sha256) == 64

        runs, _ = archive_mod.list_runs("db-1")
        assert len(runs) == 1
        assert runs[0]["status"] == "success"
        assert runs[0]["section_failures"] == []
        assert runs[0]["md_sha256"] == result.md_sha256

        # Same db, second run, sorted desc by generated_at.
        run2 = ReportRun(
            db_identifier="db-1",
            engine="postgresql",
            cadence="weekly",
            run_id="run-bbb",
            generated_at=datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc),
        )
        archive_mod.persist(run2, {"report.md": b"# Day 2\n\nbody"}, reports_bucket=_TEST_BUCKET)
        runs, _ = archive_mod.list_runs("db-1")
        assert [r["report_run_id"] for r in runs] == ["run-bbb", "run-aaa"]
    finally:
        archive_mod.set_backend_for_testing(None)


def test_persist_requires_report_md():
    archive_mod.set_backend_for_testing(_InMemoryBackend())
    try:
        run = ReportRun(
            db_identifier="db-1",
            engine="postgresql",
            cadence="manual",
            run_id="run-x",
            generated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
        )
        try:
            archive_mod.persist(run, {}, reports_bucket=_TEST_BUCKET)
        except ValueError as e:
            assert "report.md" in str(e)
        else:
            assert False, "expected ValueError"
    finally:
        archive_mod.set_backend_for_testing(None)


def test_persist_refuses_without_a_configured_bucket(monkeypatch, tmp_path):
    """There must be no guessable default bucket name.

    A predictable name such as "dbops-reports" can be registered by anyone in
    any AWS account, so falling back to one could send report artifacts to a
    bucket an outsider controls.
    """
    monkeypatch.delenv(archive_mod.BUCKET_ENV, raising=False)
    # Point config at a file with no reports.bucket so the lookup returns None.
    empty_config = tmp_path / "config.yaml"
    empty_config.write_text("reports: {}\n", encoding="utf-8")
    monkeypatch.setenv("ADMIN_OPS_CONFIG_PATH", str(empty_config))
    require_mod._reset_cache()

    archive_mod.set_backend_for_testing(_InMemoryBackend())
    try:
        run = ReportRun(
            db_identifier="db-1",
            engine="postgresql",
            cadence="manual",
            run_id="run-y",
            generated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError) as excinfo:
            archive_mod.persist(run, {"report.md": b"# x"})
        assert archive_mod.BUCKET_ENV in str(excinfo.value)
    finally:
        archive_mod.set_backend_for_testing(None)
        require_mod._reset_cache()


def test_bucket_comes_from_the_environment_when_not_passed(monkeypatch):
    """REPORTS_BUCKET is honoured so deployers need not edit config.yaml."""
    monkeypatch.setenv(archive_mod.BUCKET_ENV, _TEST_BUCKET)
    backend = _InMemoryBackend()
    archive_mod.set_backend_for_testing(backend)
    try:
        run = ReportRun(
            db_identifier="db-2",
            engine="mysql",
            cadence="manual",
            run_id="run-z",
            generated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
        )
        result = archive_mod.persist(run, {"report.md": b"# x"})
        assert result.s3_prefix.startswith(f"s3://{_TEST_BUCKET}/")
    finally:
        archive_mod.set_backend_for_testing(None)
