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

"""Git ingester for the Change Feed (R4.3).

Scans commit history (or a single commit / a webhook push payload) and
emits one ChangeEvent per commit per matching file group. Tracks changes
to the files that alter SQL behaviour or DB infrastructure:

    deploy/*/agent.py                      -> agent tool code (medium)
    infra/*.yaml, infra/*.yml              -> DB infra as code (high)
    infra/agent-permissions-policy.json    -> IAM policy (high)
    config.yaml                            -> fleet config (high)
    src/admin_ops/registry/templates/**    -> SQL templates (medium)
    src/registry/templates/**              -> SQL templates (medium, legacy path)

Severity rules (R4.3): IAM / secrets / infra -> high; template / agent
code -> medium.

This module is import-safe without AWS: it shells out to `git` and writes
through the change-feed store, whose dev backend is a local JSON file.

Validates: R4.3, R4.7, R4.9.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from src.admin_ops.changefeed.change_event import ChangeEvent, make_event_id
from src.admin_ops.changefeed import store

LOG = logging.getLogger(__name__)

# Repo root = three parents up from this file
# (src/admin_ops/changefeed/ingest/git.py -> repo root).
_REPO_ROOT = Path(__file__).resolve().parents[4]


# (compiled matcher, category label, severity, engine-or-None)
_RULES: list[tuple[re.Pattern[str], str, str, str | None]] = [
    (re.compile(r"^deploy/([a-z]+)_agent/agent\.py$"), "agent_code", "medium", None),
    (re.compile(r"^infra/agent-permissions-policy\.json$"), "iam_policy", "high", None),
    (re.compile(r"^infra/.*\.ya?ml$"), "db_infra", "high", None),
    (re.compile(r"^config\.yaml$"), "fleet_config", "high", None),
    (
        re.compile(r"^src/admin_ops/registry/templates/([a-z]+)/.*\.ya?ml$"),
        "sql_template",
        "medium",
        None,
    ),
    (
        re.compile(r"^src/registry/templates/([a-z]+)/.*\.ya?ml$"),
        "sql_template",
        "medium",
        None,
    ),
]

_ENGINES = {"postgresql", "mysql", "oracle", "dynamodb"}


def _classify(path: str) -> tuple[str, str, str | None] | None:
    """Return (category, severity, engine) for a tracked path, or None."""
    for pattern, category, severity, _engine in _RULES:
        m = pattern.match(path)
        if not m:
            continue
        engine = None
        if m.groups():
            cand = m.group(1)
            if cand in _ENGINES:
                engine = cand
        return category, severity, engine
    return None


# Git revision names: SHAs, tags, branches, and the ``~``/``^`` suffixes. Kept
# deliberately narrow, and a leading ``-`` is refused separately below because
# git would read such a value as an option rather than a revision.
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^@-]{0,200}$")


def _validate_revision(revision: str) -> str:
    """Return ``revision`` unchanged, or raise if it is not a safe revision name.

    No shell is involved in :func:`_git`, so this is not about shell escaping.
    It closes *argument* injection: ``git log`` reads a leading ``-`` as an
    option, so an unchecked value could turn a history walk into a different
    command invocation. The current only caller of :func:`ingest_history` passes
    no revision at all, so this is a guard against a future wiring of the
    parameter to a request or an agent tool rather than a live exposure.
    """
    if not isinstance(revision, str) or not _REVISION_RE.match(revision):
        raise ValueError(
            f"Invalid git revision {revision!r}: must start with an alphanumeric "
            "character and contain only [A-Za-z0-9._/~^@-]."
        )
    return revision


def _git(args: list[str]) -> str:
    """Run a read-only ``git`` command in the repository and return stdout.

    ``args`` is built inside this module. Most call sites pass a literal
    subcommand list; :func:`ingest_history` interpolates its ``since``
    parameter, which is why that function validates it first (see
    :func:`_validate_revision`).

    The argv form means no shell is involved, so shell metacharacters are inert.
    The residual concern with an interpolated value is *argument* injection: a
    value beginning with ``-`` is read by git as an option rather than as a
    revision. Anything added here that carries external input must be validated
    the same way.
    """
    # B603/B607: argv form with shell=True absent, so no shell metacharacter can
    # be interpreted; `args` carries no external input (see docstring). `git` is
    # resolved via PATH deliberately, since an absolute path would break across
    # macOS/Homebrew, Windows, and CI images.
    out = subprocess.run(  # nosec B603 B607
        ["git", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def _commit_meta(sha: str) -> tuple[str, datetime, str]:
    """Return (author, timestamp_utc, subject) for a commit."""
    raw = _git(["show", "-s", "--format=%an|%aI|%s", sha]).strip()
    author, iso, subject = raw.split("|", 2)
    ts = datetime.fromisoformat(iso).astimezone(timezone.utc)
    return author, ts, subject


def _changed_files(sha: str) -> list[str]:
    out = _git(["show", "--name-only", "--format=", sha])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _commit_url(sha: str) -> str:
    """Best-effort web URL for the commit, derived from the origin remote.

    Never embeds account/resource ids -- only the public remote path.
    """
    try:
        remote = _git(["config", "--get", "remote.origin.url"]).strip()
    except subprocess.CalledProcessError:
        remote = ""
    # git@host:group/repo.git  ->  https://host/group/repo/-/commit/<sha>
    m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}/-/commit/{sha}"
    m = re.match(r"https?://([^/]+)/(.+?)(?:\.git)?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}/-/commit/{sha}"
    return f"commit:{sha}"


def _events_for_commit(sha: str) -> list[ChangeEvent]:
    """Build ChangeEvents for one commit -- one per matching category group."""
    author, ts, subject = _commit_meta(sha)
    files = _changed_files(sha)

    # Group matching files by (category, severity, engine).
    groups: dict[tuple[str, str, str | None], list[str]] = {}
    for f in files:
        hit = _classify(f)
        if hit is None:
            continue
        groups.setdefault(hit, []).append(f)

    events: list[ChangeEvent] = []
    short = sha[:10]
    url = _commit_url(sha)
    for (category, severity, engine), matched in sorted(
        groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "")
    ):
        resource_id = f"{category}:{matched[0]}" if len(matched) == 1 else f"{category}:{len(matched)} files"
        files_desc = matched[0] if len(matched) == 1 else f"{len(matched)} {category} files"
        summary = f"[{short}] {subject[:120]} (changed {files_desc})"
        events.append(
            ChangeEvent(
                event_id=make_event_id("git", author, ts, f"{sha}:{category}:{engine}"),
                source="git",
                actor=author[:128],
                timestamp=ts,
                engine=engine,
                resource_id=resource_id[:256],
                severity=severity,  # type: ignore[arg-type]
                summary=summary[:512],
                details_url=url[:2048],
                raw_payload_ref=f"git:{sha}",
            )
        )
    return events


def ingest_commit(sha: str) -> int:
    """Ingest a single commit. Returns the number of new events written."""
    written = 0
    for ev in _events_for_commit(sha):
        try:
            if store.put_event(ev):
                written += 1
        except Exception as exc:  # noqa: BLE001 - one bad event never halts ingest (R4.9)
            LOG.warning("git ingest: failed to write event for %s: %s", sha, exc)
    return written


def ingest_history(since: str | None = None, max_commits: int = 200) -> dict:
    """Walk commit history and ingest every matching commit.

    `since` is any git revision range start (e.g. a tag or SHA). When
    None, walks the most recent `max_commits` commits. Idempotent: events
    use deterministic ids so re-running never duplicates (R4.6).
    """
    rev_args = ["log", "--format=%H", f"-n{int(max_commits)}"]
    if since:
        rev_args = ["log", "--format=%H", f"{_validate_revision(since)}..HEAD"]
    shas = [s.strip() for s in _git(rev_args).splitlines() if s.strip()]
    total_events = 0
    commits_with_events = 0
    for sha in shas:
        n = ingest_commit(sha)
        if n:
            commits_with_events += 1
        total_events += n
    return {
        "commits_scanned": len(shas),
        "commits_with_changes": commits_with_events,
        "events_written": total_events,
    }


def iter_matching_paths(files: Iterable[str]) -> list[tuple[str, str, str, str | None]]:
    """Helper for tests: return (path, category, severity, engine) matches."""
    out: list[tuple[str, str, str, str | None]] = []
    for f in files:
        hit = _classify(f)
        if hit is not None:
            out.append((f, *hit))
    return out
