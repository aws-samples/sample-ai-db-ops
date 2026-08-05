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

"""Property P7 — report rendering determinism.

For every fixed input bundle and fixed `(generated_at, run_id)` pair,
two `render_report` calls return byte-identical Markdown.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st

from src.admin_ops.reports.generator import render_report


def _bundle_strategy() -> st.SearchStrategy[dict]:
    return st.fixed_dictionaries(
        {
            "summary": st.dictionaries(
                keys=st.sampled_from(
                    ["uptime_days", "tables_count", "blocking_count", "vacuum_lag_minutes"]
                ),
                values=st.one_of(st.integers(min_value=0, max_value=10**6), st.text(max_size=40)),
                min_size=0,
                max_size=4,
            ),
            "top_slow_queries": st.lists(
                st.fixed_dictionaries(
                    {
                        "query_id": st.text(alphabet="0123456789abcdef", min_size=4, max_size=10),
                        "preview": st.text(min_size=0, max_size=40),
                        "calls": st.integers(min_value=0, max_value=10**5),
                        "mean_time_sec": st.floats(
                            min_value=0.0, max_value=1000.0,
                            allow_nan=False, allow_infinity=False,
                        ),
                        "total_time_sec": st.floats(
                            min_value=0.0, max_value=10**6,
                            allow_nan=False, allow_infinity=False,
                        ),
                    }
                ),
                min_size=0,
                max_size=8,
            ),
            "blocking_incidents": st.lists(
                st.fixed_dictionaries(
                    {
                        "blocker_pid": st.integers(min_value=1, max_value=99999),
                        "victim_pid": st.integers(min_value=1, max_value=99999),
                        "blocker_query": st.text(min_size=0, max_size=40),
                        "wait_seconds": st.floats(
                            min_value=0.0, max_value=3600.0,
                            allow_nan=False, allow_infinity=False,
                        ),
                    }
                ),
                min_size=0,
                max_size=5,
            ),
            "unused_indexes": st.lists(
                st.fixed_dictionaries(
                    {
                        "schema": st.sampled_from(["public", "shop", "audit"]),
                        "table": st.text(alphabet="abcdef", min_size=1, max_size=8),
                        "index": st.text(alphabet="abcdef_", min_size=1, max_size=12),
                        "size_mb": st.floats(
                            min_value=0.0, max_value=10**4,
                            allow_nan=False, allow_infinity=False,
                        ),
                        "scans": st.integers(min_value=0, max_value=10**6),
                    }
                ),
                min_size=0,
                max_size=5,
            ),
            "capacity_headroom": st.dictionaries(
                keys=st.sampled_from(["cpu_pct", "free_storage_gb", "iops_pct"]),
                values=st.floats(
                    min_value=0.0, max_value=100.0,
                    allow_nan=False, allow_infinity=False,
                ),
                min_size=0,
                max_size=3,
            ),
            "vacuum_undo_status": st.lists(
                st.fixed_dictionaries(
                    {
                        "object": st.text(min_size=1, max_size=20),
                        "metric": st.sampled_from(["dead_tuples", "last_vacuum_age_min"]),
                        "value": st.floats(
                            min_value=0.0, max_value=10**6,
                            allow_nan=False, allow_infinity=False,
                        ),
                    }
                ),
                min_size=0,
                max_size=5,
            ),
            "tier3_ops": st.lists(
                st.fixed_dictionaries(
                    {
                        "timestamp": st.sampled_from(
                            ["2026-05-20T10:00:00Z", "2026-05-21T11:30:00Z"]
                        ),
                        "actor": st.text(alphabet="abc", min_size=1, max_size=8),
                        "tool": st.sampled_from(["create_index", "execute_sql"]),
                        "outcome": st.sampled_from(["ok", "denied"]),
                        "summary": st.text(min_size=0, max_size=40),
                    }
                ),
                min_size=0,
                max_size=4,
            ),
        }
    )


@settings(deadline=None, max_examples=80)
@given(bundle=_bundle_strategy())
def test_p7_deterministic(bundle):
    args = dict(
        bundle=bundle,
        db_identifier="db-1",
        engine="postgresql",
        cadence="weekly",
        run_id="run-fixed-1",
        generated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    body1, run1 = render_report(**args)
    body2, run2 = render_report(**args)
    assert body1 == body2
    assert run1.status == run2.status
