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

"""Property tests for P14 / R7.1 / R7.2: no AWS account or resource IDs in
tracked files.

Two complementary layers:

1. The repo-clean invariant — walk every tracked file (skipping the
   documented allowlist) via the reusable functions in
   `scripts/check_no_resource_ids.py` and assert that none of the regex
   patterns produce a hit, and that the script exits 0. This is the P14
   guarantee for the repository's current state (no randomness — the input
   space is the whole repo).

2. A Hypothesis property layer over the matcher itself — for generated
   strings that DO match a pattern but are NOT in the allowlist (random
   12-digit accounts that aren't the docs placeholder, random vpc-/subnet-/
   sg- hex IDs, ARNs carrying a non-docs account), `scan_file` reports a
   violation; and for the documented allowlisted placeholders it reports
   none. This pins R7.1/R7.2 behaviour independent of repo contents.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# Reuse the script as a library — it's importable since `scripts/` is on
# sys.path when invoked via pytest from the repo root.
SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "check_no_resource_ids.py"
sys.path.insert(0, str(SCRIPT_PATH.parent))

from check_no_resource_ids import (  # type: ignore[import-not-found]
    ALLOW,
    ALLOW_ARN_ACCOUNT_IDS,
    PATTERNS,
    git_tracked_files,
    main as check_main,
    scan_file,
    should_scan,
)


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return SCRIPT_PATH.parent.parent


def test_no_resource_ids_in_tracked_files(repo_root: Path) -> None:
    failures: list[str] = []
    for path in git_tracked_files(repo_root):
        if not should_scan(path, repo_root):
            continue
        for lineno, matched, label in scan_file(path):
            failures.append(
                f"{path.relative_to(repo_root)}:{lineno} {label} matched {matched!r}"
            )
    assert not failures, (
        "P14 violation — tracked files contain AWS resource IDs:\n  "
        + "\n  ".join(failures)
    )


def test_script_is_executable() -> None:
    """Sanity: the checker must exit 0 on the current redacted repo state.

    Invoked in-process (no subprocess) so there is no shell-out to audit and
    the test runs faster.
    """
    exit_code = check_main(["--all"])
    assert exit_code == 0, (
        f"check_no_resource_ids.main(['--all']) returned {exit_code}; "
        "tracked source contains an AWS account/resource ID or concrete ARN."
    )


# --------------------------------------------------------------------------
# Hypothesis property layer over the matcher (R7.1 / R7.2)
# --------------------------------------------------------------------------
#
# `scan_file` is the single production matcher: it applies PATTERNS, honours
# the ALLOW set, and exempts ARNs whose account segment is a documented
# placeholder. We exercise it directly by writing one generated line into a
# temp file and asserting on the violations it reports. This keeps the test
# faithful to production behaviour rather than re-implementing the regexes.


def _scan_text(text: str) -> list[tuple[int, str, str]]:
    """Write ``text`` to a temp file and return scan_file's violations.

    Manages its own temp file (rather than the function-scoped ``tmp_path``
    fixture) so it is safe to call from inside Hypothesis ``@given`` tests.
    """
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "candidate.txt"
        target.write_text(text, encoding="utf-8")
        return scan_file(target)


def _matched_values(text: str) -> set[str]:
    return {value for _lineno, value, _label in _scan_text(text)}


_HEX = "0123456789abcdef"

# A bare 12-digit account ID, not the documented placeholder.
_account_ids = st.text(alphabet="0123456789", min_size=12, max_size=12)

# vpc-/subnet-/sg- style IDs: a literal prefix plus 8–17 hex chars.
_hex_suffix = st.text(alphabet=_HEX, min_size=8, max_size=17)

# 12-digit account segment for ARNs that is NOT a documented placeholder.
_arn_accounts = st.text(alphabet="0123456789", min_size=12, max_size=12)
_arn_services = st.sampled_from(["s3", "rds", "iam", "secretsmanager", "dynamodb"])
_arn_regions = st.sampled_from(["us-east-1", "us-west-2", "eu-west-1"])


@settings(deadline=None, max_examples=200)
@given(account=_account_ids)
def test_non_placeholder_account_id_is_flagged(account: str) -> None:
    """R7.1: a 12-digit account that isn't the docs placeholder is a hit."""
    assume(account not in ALLOW)
    matched = _matched_values(f"account = {account} ;")
    assert account in matched


@settings(deadline=None, max_examples=200)
@given(prefix=st.sampled_from(["vpc", "subnet", "sg"]), suffix=_hex_suffix)
def test_non_placeholder_resource_id_is_flagged(prefix: str, suffix: str) -> None:
    """R7.1: vpc-/subnet-/sg- IDs with real hex suffixes are hits."""
    value = f"{prefix}-{suffix}"
    assume(value not in ALLOW)
    matched = _matched_values(f"resource: {value}\n")
    assert value in matched


@settings(deadline=None, max_examples=200)
@given(account=_arn_accounts, service=_arn_services, region=_arn_regions)
def test_arn_with_non_docs_account_is_flagged(
    account: str, service: str, region: str
) -> None:
    """R7.2: an ARN whose account segment is not a documented placeholder
    is reported as a Concrete ARN violation."""
    assume(account not in ALLOW_ARN_ACCOUNT_IDS)
    arn = f"arn:aws:{service}:{region}:{account}:resource/thing"
    violations = _scan_text(arn)
    labels = {label for _lineno, _value, label in violations}
    assert "Concrete ARN" in labels


@settings(deadline=None, max_examples=50)
@given(placeholder=st.sampled_from(sorted(ALLOW)))
def test_allowlisted_placeholders_are_not_flagged(placeholder: str) -> None:
    """R7.1: documented placeholders in the ALLOW set never count as hits."""
    matched = _matched_values(f"value = {placeholder}\n")
    assert placeholder not in matched


@settings(deadline=None, max_examples=200)
@given(
    account=st.sampled_from(sorted(ALLOW_ARN_ACCOUNT_IDS)),
    service=_arn_services,
    region=_arn_regions,
)
def test_arn_with_docs_account_is_not_flagged(
    account: str, service: str, region: str
) -> None:
    """R7.2: an ARN whose account segment is a documented placeholder
    account is an example and produces no violation."""
    arn = f"arn:aws:{service}:{region}:{account}:secret:thing-XXXXXX"
    violations = _scan_text(arn)
    assert violations == []
