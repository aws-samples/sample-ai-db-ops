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

"""Property P5 — SQL_Editor tier classification monotonicity.

For every parsable SQL statement s, classify(s) is invariant under
benign edits: appending whitespace, changing case, prepending comments.
"""

from __future__ import annotations

import string

from hypothesis import given, settings, strategies as st

from src.admin_ops.admin.sql.classifier import classify

_KEYWORDS = [
    "SELECT", "SHOW", "EXPLAIN", "DESCRIBE", "WITH",
    "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP",
    "TRUNCATE", "GRANT", "REVOKE", "CALL", "EXEC", "MERGE",
    "VACUUM", "ANALYZE",
]

_REST_ALPHA = string.ascii_letters + string.digits + " ()"


def _stmt_for(kw: str, rest: str) -> str:
    return f"{kw} {rest}"


@settings(deadline=None, max_examples=200)
@given(
    keyword=st.sampled_from(_KEYWORDS),
    rest=st.text(alphabet=_REST_ALPHA, min_size=0, max_size=80),
    extra_ws=st.text(alphabet=" \t\n", min_size=0, max_size=8),
    upper=st.booleans(),
    leading_comment=st.booleans(),
)
def test_p5_classify_is_invariant_under_benign_edits(
    keyword: str,
    rest: str,
    extra_ws: str,
    upper: bool,
    leading_comment: bool,
) -> None:
    base = _stmt_for(keyword, rest)
    edited = base
    if extra_ws:
        edited = extra_ws + edited + extra_ws
    if not upper:
        edited = edited.lower()
    if leading_comment:
        edited = "-- a benign comment\n" + edited

    # Engines whose classifier handles SQL keywords.
    for engine in ("mysql", "oracle"):
        a = classify(engine, base)
        b = classify(engine, edited)
        assert a.tier == b.tier, (
            f"engine={engine} base={base!r} edited={edited!r} "
            f"a.tier={a.tier} b.tier={b.tier}"
        )


def test_known_keyword_classifications() -> None:
    for kw, expected in [
        ("SELECT 1", "tier_1_read"),
        ("show tables", "tier_1_read"),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "tier_1_read"),
        ("INSERT INTO t VALUES (1)", "tier_3_act"),
        ("DROP TABLE t", "tier_3_act"),
        ("explain analyze select 1", "tier_1_read"),
    ]:
        c = classify("mysql", kw)
        assert c.tier == expected, (kw, c)


def test_empty_body_is_tier_3() -> None:
    assert classify("postgresql", "").tier == "tier_3_act"
    assert classify("postgresql", "   \n\t").tier == "tier_3_act"


def test_unsupported_engine_falls_closed() -> None:
    assert classify("redshift", "SELECT 1").tier == "tier_3_act"
