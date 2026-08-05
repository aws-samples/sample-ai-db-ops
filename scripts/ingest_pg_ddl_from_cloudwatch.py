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

"""Pull recent Postgres DDL log events from CloudWatch and ingest them.

This is the runnable equivalent of the CloudWatch Logs subscription
Lambda: it reads the `/aws/rds/cluster/<cluster>/postgresql` log group,
feeds each record through `pg_ddl.ingest_log_event`, and writes
`database`-source ChangeEvents to the (dev/JSON) Change Feed.

Requires ADMIN_DEV_BYPASS=1 so the store uses the local JSON backend.

Usage:
    ADMIN_DEV_BYPASS=1 .venv/bin/python scripts/ingest_pg_ddl_from_cloudwatch.py
    ADMIN_DEV_BYPASS=1 .venv/bin/python scripts/ingest_pg_ddl_from_cloudwatch.py --minutes 120
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.admin_ops.changefeed.ingest import pg_ddl  # noqa: E402

REGION = "us-east-1"
DB_IDENTIFIER = "database-test"
LOG_GROUP = f"/aws/rds/cluster/{DB_IDENTIFIER}/postgresql"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=int, default=180, help="look-back window")
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--log-group", default=LOG_GROUP)
    args = ap.parse_args()

    logs = boto3.client("logs", region_name=args.region)
    start_ms = int((time.time() - args.minutes * 60) * 1000)

    written = 0
    scanned = 0
    token = None
    while True:
        kw = dict(
            logGroupName=args.log_group,
            startTime=start_ms,
            limit=1000,
        )
        if token:
            kw["nextToken"] = token
        resp = logs.filter_log_events(**kw)
        for ev in resp.get("events", []):
            scanned += 1
            if pg_ddl.ingest_log_event(
                message=ev.get("message", ""),
                timestamp_ms=ev.get("timestamp"),
                db_identifier=DB_IDENTIFIER,
                log_stream=ev.get("logStreamName"),
            ):
                written += 1
        token = resp.get("nextToken")
        if not token:
            break

    print(f"PostgreSQL DDL ingest from CloudWatch ({args.log_group}):")
    print(f"  log records scanned : {scanned}")
    print(f"  DDL events written  : {written}")


if __name__ == "__main__":
    main()
