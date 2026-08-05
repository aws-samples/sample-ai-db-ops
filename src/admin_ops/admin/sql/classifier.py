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

"""Tier classifier for SQL_Editor input.

Engines:
- PostgreSQL: `pglast` if installed, falls back to leading-keyword tokenizer
- MySQL:      regex tokenizer over `sqlparse`-style stripping
- Oracle:     regex tokenizer (`oracledb.Cursor.parse()` is too expensive
              for client-side classification; the agent path gates the
              statement through `Tier3ApprovalHook` before execution)
- DynamoDB:   the body is a JSON `{"Operation": "...", ...}` map; we
              key off the Operation field

Fail closed: when the parser raises, throws, or the leading keyword is
not in the known map, the result is `tier_3_act`. R2.13.

Validates: R2.10–R2.13, R2.16, P5.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

LOG = logging.getLogger(__name__)


Tier = Literal["tier_1_read", "tier_2_advise", "tier_3_act"]


@dataclass(frozen=True)
class Classification:
    tier: Tier
    leading_keyword: str | None
    reason: str


_TIER_BY_KEYWORD: dict[str, Tier] = {
    "SELECT": "tier_1_read",
    "SHOW": "tier_1_read",
    "EXPLAIN": "tier_1_read",
    "DESCRIBE": "tier_1_read",
    "DESC": "tier_1_read",
    "WITH": "tier_1_read",  # WITH ... SELECT (CTE)
    "VALUES": "tier_1_read",
    "RECOMMEND": "tier_2_advise",
    "INSERT": "tier_3_act",
    "UPDATE": "tier_3_act",
    "DELETE": "tier_3_act",
    "CREATE": "tier_3_act",
    "ALTER": "tier_3_act",
    "DROP": "tier_3_act",
    "TRUNCATE": "tier_3_act",
    "GRANT": "tier_3_act",
    "REVOKE": "tier_3_act",
    "CALL": "tier_3_act",
    "EXEC": "tier_3_act",
    "EXECUTE": "tier_3_act",
    "MERGE": "tier_3_act",
    "REPLACE": "tier_3_act",
    "REINDEX": "tier_3_act",
    "VACUUM": "tier_3_act",
    "ANALYZE": "tier_3_act",
    "COMMIT": "tier_3_act",
    "ROLLBACK": "tier_3_act",
    "BEGIN": "tier_3_act",
}


_DDB_OP_TO_TIER: dict[str, Tier] = {
    # Read-only operations.
    "GETITEM": "tier_1_read",
    "QUERY": "tier_1_read",
    "SCAN": "tier_1_read",
    "DESCRIBETABLE": "tier_1_read",
    "BATCHGETITEM": "tier_1_read",
    "LISTTABLES": "tier_1_read",
    # Mutating operations.
    "PUTITEM": "tier_3_act",
    "UPDATEITEM": "tier_3_act",
    "DELETEITEM": "tier_3_act",
    "BATCHWRITEITEM": "tier_3_act",
    "UPDATETABLE": "tier_3_act",
    "DELETETABLE": "tier_3_act",
    "CREATETABLE": "tier_3_act",
    "CREATEBACKUP": "tier_3_act",
    "EXPORTTABLETOPOINTINTIME": "tier_3_act",
    "UPDATECONTRIBUTORINSIGHTS": "tier_3_act",
}


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_LEADING_WORD = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\b")


def _strip_comments_and_whitespace(body: str) -> str:
    body = _BLOCK_COMMENT.sub(" ", body)
    body = _LINE_COMMENT.sub("", body)
    return body.strip()


def _leading_keyword_generic(body: str) -> str | None:
    cleaned = _strip_comments_and_whitespace(body)
    m = _LEADING_WORD.match(cleaned)
    if not m:
        return None
    return m.group(1).upper()


def _classify_postgresql(body: str) -> Classification:
    # Prefer pglast for full-grammar parsing when available.
    try:
        import pglast  # type: ignore

        try:
            tree = pglast.parse_sql(body)
        except Exception as exc:  # noqa: BLE001
            return Classification("tier_3_act", None, f"pglast_parse_error: {exc}")
        if not tree:
            return Classification("tier_3_act", None, "pglast_empty_tree")
        first = tree[0]
        # First node's stmt class name as the keyword (e.g. SelectStmt → SELECT).
        node_name = first.stmt.__class__.__name__.upper()
        if "SELECT" in node_name:
            kw = "SELECT"
        elif "INSERT" in node_name:
            kw = "INSERT"
        elif "UPDATE" in node_name:
            kw = "UPDATE"
        elif "DELETE" in node_name:
            kw = "DELETE"
        elif "EXPLAIN" in node_name:
            kw = "EXPLAIN"
        elif "VARIABLESHOW" in node_name or node_name.startswith("SHOW"):
            kw = "SHOW"
        elif "CREATE" in node_name:
            kw = "CREATE"
        elif "ALTER" in node_name:
            kw = "ALTER"
        elif "DROP" in node_name:
            kw = "DROP"
        elif "TRUNCATE" in node_name:
            kw = "TRUNCATE"
        elif "VACUUM" in node_name:
            kw = "VACUUM"
        else:
            kw = _leading_keyword_generic(body) or ""
    except ImportError:
        kw = _leading_keyword_generic(body) or ""
    if not kw:
        return Classification("tier_3_act", None, "no_leading_keyword")
    tier = _TIER_BY_KEYWORD.get(kw, "tier_3_act")
    reason = "matched" if kw in _TIER_BY_KEYWORD else "unrecognized_keyword"
    return Classification(tier, kw, reason)


def _classify_keyword_only(engine: str, body: str) -> Classification:
    kw = _leading_keyword_generic(body)
    if not kw:
        return Classification("tier_3_act", None, "no_leading_keyword")
    tier = _TIER_BY_KEYWORD.get(kw, "tier_3_act")
    reason = "matched" if kw in _TIER_BY_KEYWORD else "unrecognized_keyword"
    return Classification(tier, kw, reason)


def _classify_dynamodb(body: str) -> Classification:
    try:
        obj = json.loads(body)
    except json.JSONDecodeError as exc:
        return Classification("tier_3_act", None, f"json_parse_error: {exc}")
    op = obj.get("Operation") if isinstance(obj, dict) else None
    if not isinstance(op, str) or not op:
        return Classification("tier_3_act", None, "missing_operation")
    key = op.upper()
    tier = _DDB_OP_TO_TIER.get(key, "tier_3_act")
    reason = "matched" if key in _DDB_OP_TO_TIER else "unrecognized_operation"
    return Classification(tier, op, reason)


def classify(engine: str, body: str) -> Classification:
    """Classify a SQL or DynamoDB statement body into a Tier.

    Always returns; never raises. Fail-closed default is `tier_3_act`.
    """
    if not isinstance(body, str) or not body.strip():
        return Classification("tier_3_act", None, "empty_body")
    if engine == "postgresql":
        return _classify_postgresql(body)
    if engine in ("mysql", "oracle"):
        return _classify_keyword_only(engine, body)
    if engine == "dynamodb":
        return _classify_dynamodb(body)
    return Classification("tier_3_act", None, "unsupported_engine")
