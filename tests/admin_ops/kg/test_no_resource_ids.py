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

"""Property P-KG6 (R4.1, R4.8, R7.6, R10.3) — no-resource-id-in-source invariant.

No file under the dba-knowledge-graph spec, ``src/admin_ops/kg/``, the DBA View
UI (``ui/src/app/dba/``, ``ui/src/components/dba/``, ``ui/src/lib/dba/``), or
the seeded Ticket dataset matches a 12-digit account id, ``vpc-``/``subnet-``/
``sg-`` id, or ARN pattern (documented placeholders allowed).

This reuses the exact detection rules and allowlist from
``scripts/check_no_resource_ids.py`` so the property and the CI gate stay in
lockstep; it is a fast, static, no-AWS scan.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Load the redaction script as a module to reuse its PATTERNS / ALLOW rules.
_SCRIPT = _REPO_ROOT / "scripts" / "check_no_resource_ids.py"
_spec = importlib.util.spec_from_file_location("_redaction_check", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_redaction = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_redaction)


# The feature surfaces P-KG6 covers.
_SCAN_ROOTS = [
    _REPO_ROOT / ".kiro" / "specs" / "dba-knowledge-graph",
    _REPO_ROOT / "src" / "admin_ops" / "kg",
    _REPO_ROOT / "ui" / "src" / "app" / "dba",
    _REPO_ROOT / "ui" / "src" / "components" / "dba",
    _REPO_ROOT / "ui" / "src" / "lib" / "dba",
]
_SEEDED_DATASET = _REPO_ROOT / "src" / "admin_ops" / "kg" / "data" / "seeded_tickets.json"


def _feature_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if _redaction.should_scan(path, _REPO_ROOT):
                files.append(path)
    if _SEEDED_DATASET.exists() and _SEEDED_DATASET not in files:
        files.append(_SEEDED_DATASET)
    return files


# Feature: dba-knowledge-graph, Property P-KG6: no-resource-id-in-source invariant
def test_pkg6_no_resource_ids_in_feature_source() -> None:
    files = _feature_files()
    # Guard: ensure the scan actually covers files (paths didn't silently move).
    assert files, "expected to scan dba-knowledge-graph feature files"

    violations: list[str] = []
    for path in files:
        for lineno, value, label in _redaction.scan_file(path):
            rel = path.relative_to(_REPO_ROOT)
            violations.append(f"{rel}:{lineno}: {label} matched {value!r}")

    assert not violations, "resource id(s) leaked into feature source:\n" + "\n".join(
        violations
    )


def test_pkg6_seeded_dataset_is_placeholder_only() -> None:
    assert _SEEDED_DATASET.exists()
    assert _redaction.scan_file(_SEEDED_DATASET) == []
