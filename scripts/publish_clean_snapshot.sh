#!/usr/bin/env bash
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

#
# publish_clean_snapshot.sh
# -------------------------------------------------------------------------
# Produce a SINGLE-COMMIT, history-free snapshot of the current tree for an
# external / public release, then (optionally) push it to a public remote.
#
# WHY THIS EXISTS
#   The internal repo's git history still contains pre-redaction commits
#   (real AWS account id, RDS endpoint hash, VPC/subnet/SG ids, alias).
#   Redacting at the tip does NOT remove those from history -- `git log -S`
#   recovers them. For a public release the accepted bar is "no internal
#   identifiers anywhere in history". This script creates an ORPHAN root
#   commit: the published repo starts at commit #1 with the clean tree and
#   carries none of the prior commits.
#
# WHAT IT DOES NOT DO  (by design -- these would risk corrupting the repo)
#   * It NEVER rewrites or force-pushes the internal repo's branches.
#   * It NEVER touches `main`, `feat/*`, `origin`, or `upstream`.
#   * It NEVER deletes anything. Worst case it leaves an extra local
#     branch you can delete with `git branch -D`.
#
# SAFETY MODEL
#   * Dry-run by default. It only mutates anything when you pass --confirm.
#   * Even with --confirm it stops before pushing unless you ALSO pass
#     --push <remote-url>. Creating the local snapshot branch and pushing
#     are two separate, explicit opt-ins.
#   * Re-runnable: the snapshot branch name is timestamped so a re-run
#     never clobbers a previous one.
#
# USAGE
#   # 1. See exactly what would happen (no changes):
#   bash scripts/publish_clean_snapshot.sh
#
#   # 2. Build the local single-commit snapshot branch (no push):
#   bash scripts/publish_clean_snapshot.sh --confirm
#
#   # 3. Build it AND push to the public repo once approved:
#   bash scripts/publish_clean_snapshot.sh --confirm \
#        --push git@github.com:<org>/<public-repo>.git
#
# PRECONDITIONS (the script verifies these and aborts if any fail)
#   * Working tree is clean (no uncommitted changes).
#   * The redaction guard (scripts/check_no_resource_ids.py --all) passes.
#   * An optional name-based denylist backstop finds nothing.
# -------------------------------------------------------------------------
set -euo pipefail

# ---- resolve repo root regardless of where the script is invoked from ----
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# ---- args ----------------------------------------------------------------
CONFIRM=0
PUSH_URL=""
SOURCE_REF="HEAD"            # what to snapshot; defaults to current checkout
PUBLIC_BRANCH="main"         # branch name in the published repo
while [[ $# -gt 0 ]]; do
  case "$1" in
    --confirm) CONFIRM=1; shift ;;
    --push) PUSH_URL="${2:-}"; shift 2 ;;
    --source) SOURCE_REF="${2:-}"; shift 2 ;;
    --public-branch) PUBLIC_BRANCH="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,60p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

SNAPSHOT_BRANCH="public-snapshot-$(date -u +%Y%m%d-%H%M%S)"

say()  { printf '[publish] %s\n' "$*"; }
warn() { printf '[publish] WARNING: %s\n' "$*"; }
die()  { printf '[publish] ABORT: %s\n' "$*" >&2; exit 1; }

# ---- preconditions -------------------------------------------------------
say "Repo root: $REPO_ROOT"
say "Source ref to snapshot: $SOURCE_REF ($(git rev-parse --short "$SOURCE_REF"))"

# 1. clean working tree
if [[ -n "$(git status --porcelain)" ]]; then
  die "working tree is not clean. Commit or stash changes first."
fi

# 2. redaction guard
if [[ -x ".venv/bin/python" ]]; then PY=".venv/bin/python"; else PY="python3"; fi
say "Running redaction guard (P14)."
if ! "$PY" scripts/check_no_resource_ids.py --all; then
  die "redaction guard FAILED. The tree still contains an AWS resource id."
fi
say "Redaction guard passed."

# 3. optional name-based backstop (shapes are already covered by P14 above).
# Name-based identifiers (aliases, resource names) have no regex "shape", so
# P14 cannot catch them generically. To guard against a regression
# re-introducing a SPECIFIC known name, drop a newline-separated list of
# literal strings into `.secrets/publish_denylist.txt` (gitignored, never
# published). This script reads it if present. We deliberately do NOT embed
# any literal identifier in this file so the script itself is safe to publish.
DENYLIST_FILE="${PUBLISH_DENYLIST_FILE:-.secrets/publish_denylist.txt}"
if [[ -f "$DENYLIST_FILE" ]]; then
  say "Applying name-based backstop from $DENYLIST_FILE"
  if grep -vE '^[[:space:]]*(#|$)' "$DENYLIST_FILE" | grep -q .; then
    if git grep -nFf <(grep -vE '^[[:space:]]*(#|$)' "$DENYLIST_FILE") -- $(git ls-files) \
        >/tmp/_publish_grep.txt 2>/dev/null; then
      warn "denylist backstop found potential identifiers:"
      cat /tmp/_publish_grep.txt >&2
      die "tree is NOT clean for public release. Resolve the matches above."
    fi
    say "Denylist backstop clean."
  fi
else
  warn "No $DENYLIST_FILE present -- relying on the P14 shape-based guard only."
  warn "If you have specific internal NAMES to guard against (aliases, host"
  warn "names), create that gitignored file with one literal per line."
fi

# ---- dry run gate --------------------------------------------------------
if [[ "$CONFIRM" -ne 1 ]]; then
  cat <<EOF

------------------------------------------------------------------------
DRY RUN -- nothing was changed.

If you proceed with --confirm, the script will:
  1. Create an orphan branch  : $SNAPSHOT_BRANCH
  2. Commit the current tree ($(git rev-parse --short "$SOURCE_REF")) as a
     SINGLE root commit (no parents, no prior history).
  3. Leave you on that branch so you can inspect it
     (git log --oneline  ->  should show exactly ONE commit).

It will NOT push unless you also pass:
     --push <public-remote-url>

It will NOT modify main, feat/*, origin, or upstream in any case.

To proceed:
     bash scripts/publish_clean_snapshot.sh --confirm
------------------------------------------------------------------------
EOF
  exit 0
fi

# ---- build the orphan snapshot ------------------------------------------
ORIGINAL_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
say "Current branch saved: $ORIGINAL_BRANCH (we return here if anything fails)"

cleanup_on_error() {
  warn "Error encountered. Returning to $ORIGINAL_BRANCH."
  git checkout --quiet "$ORIGINAL_BRANCH" 2>/dev/null || true
}
trap cleanup_on_error ERR

say "Creating orphan branch $SNAPSHOT_BRANCH from $SOURCE_REF"
git checkout --orphan "$SNAPSHOT_BRANCH" "$SOURCE_REF"

# `--orphan` carries the index/worktree but no parent. Stage everything that
# is tracked at the source ref (respects .gitignore automatically).
git add -A

_MSG_FILE="$(mktemp)"
cat > "$_MSG_FILE" <<'MSG'
Initial public release

AI-powered database operations platform using the Strands Agent Framework
on Amazon Bedrock AgentCore Runtime. Manage Aurora PostgreSQL, Aurora
MySQL, Oracle EE, and DynamoDB through natural language with real-time
connections to live databases.

This is a clean single-commit snapshot prepared for external release. All
account-specific values are read from environment variables; see
ui/.env.local.example and config.yaml. No AWS account ids, ARNs, VPC /
subnet / security-group ids, RDS endpoints, or internal aliases appear in
the source or in the history of this repository.
MSG

git commit -q -F "$_MSG_FILE"
rm -f "$_MSG_FILE"

# Keep a stable secondary name too, so the push mapping is obvious.
git branch -f "${PUBLIC_BRANCH}-publish" "$SNAPSHOT_BRANCH"

trap - ERR

say "Done. Local snapshot created:"
echo
git --no-pager log --oneline --decorate -n 3
echo
SNAP_FILE_COUNT="$(git ls-files | wc -l | tr -d ' ')"
SNAP_PARENTS="$(git rev-list --parents -n1 HEAD | cut -d ' ' -f2-)"
say "Tracked file count in snapshot: $SNAP_FILE_COUNT"
say "Parent commits of snapshot (should be EMPTY): [$SNAP_PARENTS]"
echo

# ---- optional push -------------------------------------------------------
if [[ -n "$PUSH_URL" ]]; then
  say "Pushing snapshot to public remote:"
  say "  $PUSH_URL   (branch: $PUBLIC_BRANCH)"
  warn "This pushes to the PUBLIC remote only. It does not touch origin/upstream."
  # Push the orphan branch as the public branch. No --force: the public repo
  # is expected to be empty/new. If it already has content this fails
  # rather than clobber -- that is intentional.
  git push "$PUSH_URL" "$SNAPSHOT_BRANCH:refs/heads/$PUBLIC_BRANCH"
  say "Pushed."
else
  cat <<EOF

------------------------------------------------------------------------
Snapshot built locally but NOT pushed (no --push given).

Inspect it:
    git log --oneline            # exactly one commit
    git ls-files | wc -l         # file count matches the clean tree

When Security gives you the public repo URL, push with:
    git push <public-url> $SNAPSHOT_BRANCH:refs/heads/$PUBLIC_BRANCH

Return to your working branch any time:
    git checkout $ORIGINAL_BRANCH

Delete the snapshot branch if you abandon it (safe -- it is local only):
    git checkout $ORIGINAL_BRANCH && git branch -D $SNAPSHOT_BRANCH ${PUBLIC_BRANCH}-publish
------------------------------------------------------------------------
EOF
fi
