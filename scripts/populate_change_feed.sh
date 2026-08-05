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

# Populate the local (dev) Change Feed by scanning this repo's git history
# for changes to SQL templates, agent code, and DB infrastructure.
#
# Requires ADMIN_DEV_BYPASS=1 so the change-feed store uses the local
# JSON-file backend instead of DynamoDB. Idempotent -- deterministic event
# ids mean re-running never creates duplicates.
#
# Usage:
#   bash scripts/populate_change_feed.sh            # last 200 commits
#   bash scripts/populate_change_feed.sh 50         # last 50 commits
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

MAX="${1:-200}"
if [[ -x ".venv/bin/python" ]]; then PY=".venv/bin/python"; else PY="python3"; fi

ADMIN_DEV_BYPASS=1 "$PY" - "$MAX" <<'PY'
import sys
from src.admin_ops.changefeed.ingest import git

max_commits = int(sys.argv[1])
result = git.ingest_history(max_commits=max_commits)
print("Change Feed populated from git history:")
print(f"  commits scanned    : {result['commits_scanned']}")
print(f"  commits w/ changes : {result['commits_with_changes']}")
print(f"  events written     : {result['events_written']}")
PY
