#!/usr/bin/env python3
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

"""Fail the build when any tracked file embeds an AWS resource identifier.

Implements property P14 and acceptance criteria R7.1 / R7.2 of the
admin-ops-console spec: no literal AWS account / VPC / subnet / security
group IDs and no concrete ARNs in tracked source. Concrete values come
from environment variables, ``config.yaml``, or AWS Secrets Manager at
runtime, never from checked-in source.

This script is wired in two places:

  * ``.pre-commit-config.yaml`` -- runs on the staged files pre-commit
    passes as positional arguments (``pass_filenames: true``).
  * ``.gitlab-ci.yml`` (``lint:redaction``) -- runs with ``--all`` over
    every Git-tracked file. CI is the source of truth for merges.

Usage:
    scripts/check_no_resource_ids.py --all
    scripts/check_no_resource_ids.py PATH [PATH ...]

Exit status is non-zero when any scanned file matches one of the patterns
below with a value that is not in the ALLOW set.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# --- Detection rules (design.md section "No-resource-id check") -------------
#
# Each entry is (compiled regex, human-readable label). The label is shown in
# the failure message so the author knows which kind of identifier matched.
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?<!\d)\d{12}(?!\d)\b"), "AWS account ID"),
    (re.compile(r"\bvpc-[0-9a-f]{8,17}\b"), "VPC ID"),
    (re.compile(r"\bsubnet-[0-9a-f]{8,17}\b"), "Subnet ID"),
    (re.compile(r"\bsg-[0-9a-f]{8,17}\b"), "Security group ID"),
    (re.compile(r"\barn:aws:[a-z0-9-]+:[a-z0-9-]+:\d{12}:"), "Concrete ARN"),
]

# Documented placeholders that intentionally use these shapes. A match whose
# exact text is in this set is not a violation.
ALLOW: set[str] = {
    "123456789012",  # AWS docs placeholder
    "vpc-0xxxxxxxxxxxxxxxx",
    "subnet-0xxxxxxxxxxxxxxxx",
    "subnet-0yyyyyyyyyyyyyyyy",
    # Documented subnet placeholders used in README.md, deploy_all.sh and
    # infra/cloudformation-account-specific.yaml. Same intent as the x/y/z
    # variants above; the repo's example CF outputs happen to use a/b.
    "subnet-0aaaaaaaaaaaaaaaa",
    "subnet-0bbbbbbbbbbbbbbbb",
    "sg-0xxxxxxxxxxxxxxxx",
    "sg-0yyyyyyyyyyyyyyyy",
    "sg-0zzzzzzzzzzzzzzzz",
}

# Documented placeholder AWS account IDs. A *concrete ARN* whose account-id
# segment is one of these is a documented example (e.g.
# ``arn:aws:secretsmanager:us-east-1:123456789012:secret:...-XXXXXX``), not a
# real resource, so it is exempt from the "Concrete ARN" pattern. This mirrors
# ``123456789012`` already being allowed as a bare account ID. Any ARN with a
# real 12-digit account still fails (R7.1 / R7.2).
ALLOW_ARN_ACCOUNT_IDS: set[str] = {
    "123456789012",  # AWS docs placeholder account
}

# Extracts the account-id segment (5th colon-delimited field) from an ARN so
# the "Concrete ARN" allowance can check it against ALLOW_ARN_ACCOUNT_IDS.
_ARN_ACCOUNT_RE: re.Pattern[str] = re.compile(
    r"arn:aws:[a-z0-9-]+:[a-z0-9-]+:(\d{12}):"
)

# Directories never scanned (VCS internals, virtualenvs, build output).
SKIP_DIRS: set[str] = {".git", ".venv", "node_modules", ".next"}


def is_text_file(path: Path) -> bool:
    """Return True if the file looks like text (no NUL byte in first 8 KiB)."""
    try:
        with path.open("rb") as handle:
            chunk = handle.read(8192)
    except OSError:
        return False
    return b"\x00" not in chunk


def should_scan(path: Path, repo_root: Path) -> bool:
    """Decide whether a path is eligible for scanning."""
    try:
        rel_parts = path.relative_to(repo_root).parts
    except ValueError:
        rel_parts = path.parts
    if any(part in SKIP_DIRS for part in rel_parts):
        return False
    if not path.is_file():
        return False
    return is_text_file(path)


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return a list of ``(line_number, matched_value, pattern_label)``."""
    violations: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return violations
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, label in PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                if value in ALLOW:
                    continue
                # A concrete ARN whose account-id segment is a documented
                # placeholder account (e.g. 123456789012) is an example, not a
                # real resource. Any ARN with a real account still fails.
                if label == "Concrete ARN":
                    account_match = _ARN_ACCOUNT_RE.match(value)
                    if (
                        account_match
                        and account_match.group(1) in ALLOW_ARN_ACCOUNT_IDS
                    ):
                        continue
                violations.append((lineno, value, label))
    return violations


def git_tracked_files(repo_root: Path) -> list[Path]:
    """Return every Git-tracked file under ``repo_root``.

    Falls back to a directory walk (honouring SKIP_DIRS) when Git is not
    available -- e.g. a CI runner without a checkout.
    """
    try:
        # B603/B607: the argument vector is a fixed literal with no caller input,
        # and shell=True is not used, so there is nothing to inject into. `git`
        # is resolved via PATH deliberately — an absolute path would break on
        # macOS/Homebrew, Windows, and most CI images. This is a developer-run
        # guardrail script, so PATH is already as trusted as the checkout.
        result = subprocess.run(  # nosec B603 B607
            ["git", "ls-files", "-z"],
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
        names = result.stdout.decode("utf-8", "replace").split("\0")
        files = [repo_root / name for name in names if name]
        if files:
            return files
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    out: list[Path] = []
    for candidate in repo_root.rglob("*"):
        rel_parts = candidate.relative_to(repo_root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if candidate.is_file():
            out.append(candidate)
    return out


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="scan every Git-tracked file (used by CI)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="explicit files to scan (used by pre-commit)",
    )
    args = parser.parse_args(argv)

    # Repo root is the directory containing scripts/.
    repo_root = Path(__file__).resolve().parent.parent

    if args.all:
        candidates = git_tracked_files(repo_root)
    elif args.paths:
        candidates = [Path(p).resolve() for p in args.paths]
    else:
        parser.error("pass --all or one or more file paths to scan")

    failed = False
    for path in candidates:
        if not should_scan(path, repo_root):
            continue
        for lineno, value, label in scan_file(path):
            failed = True
            print(
                f"{display_path(path, repo_root)}:{lineno}: "
                f"{label} matched {value!r} "
                f"(pattern: {label})",
                file=sys.stderr,
            )

    if failed:
        print(
            "\nFAILED: tracked source contains an AWS account / resource ID "
            "or concrete ARN. Replace it with a documented placeholder and "
            "load the real value from the environment, config.yaml, or "
            "Secrets Manager at runtime.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
