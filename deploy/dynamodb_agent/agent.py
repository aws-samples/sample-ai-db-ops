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

"""DynamoDB Ops Agent — Real-time operations against Amazon DynamoDB."""

import os
import logging
import sys
import time
import boto3
from datetime import datetime, timedelta, timezone

# NOTE: BYPASS_TOOL_CONSENT is deliberately NOT set. Tier-3 (mutating) tool
# calls are gated by Tier3ApprovalHook below, which halts the agent loop until
# the operator supplies an explicit APPLY for that exact operation. Setting
# BYPASS_TOOL_CONSENT here would suppress the framework's own consent handling
# and must not be reintroduced.

from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

# Make repo root importable when launched from deploy/dynamodb_agent/.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.admin_ops.registry.loader import registry  # noqa: E402
from src.hooks.tier3_approval import (  # noqa: E402
    Tier3ApprovalHook,
    pending_approvals,
)

# ─── Template registry startup hook (R1.3) ──────────────────────────────────────
_LOG = logging.getLogger(__name__)
_t = time.monotonic()
try:
    registry.load()
    _LOG.info(
        "template registry loaded in %.1f ms (%d templates, %d failures)",
        (time.monotonic() - _t) * 1000,
        len(registry.all()),
        len(registry.failures()),
    )
except Exception as _exc:  # pragma: no cover - never block agent startup
    _LOG.warning("template registry load failed: %s; falling back to in-source defaults", _exc)

app = BedrockAgentCoreApp()

REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "dbops-orders")


def get_dynamodb():
    return boto3.client("dynamodb", region_name=REGION)


def get_cloudwatch():
    return boto3.client("cloudwatch", region_name=REGION)


SYSTEM_PROMPT = """You are an expert DynamoDB Operations Agent connected to LIVE DynamoDB tables.

All tool results are REAL data from actual AWS APIs — not simulated.

## Capabilities
- Tier 1 (Read-Only, +10 XP): List tables, describe table, consumed capacity, CloudWatch metrics, item count
- Tier 2 (Advisory, +25 XP): Capacity recommendations, access pattern analysis
- Tier 3 (Actioned, +50 XP): Modify capacity, create backup — REQUIRES APPROVAL

## Rules
1. All data is LIVE from AWS APIs. 2. Never modify capacity without approval.
3. Use emoji: 🟢 OK, 🟡 WARN, 🔴 CRITICAL
"""


@tool
def list_tables() -> dict:
    """List all DynamoDB tables in the account/region (REAL DATA)."""
    client = get_dynamodb()
    response = client.list_tables()
    tables = response.get("TableNames", [])
    return {"tables": tables, "count": len(tables), "region": REGION}


@tool
def describe_table(table_name: str) -> dict:
    """Describe a DynamoDB table — keys, GSIs, capacity, item count (REAL DATA).

    Args:
        table_name: The DynamoDB table name.
    """
    client = get_dynamodb()
    response = client.describe_table(TableName=table_name)
    table = response["Table"]

    result = {
        "table_name": table["TableName"],
        "status": table["TableStatus"],
        "item_count": table.get("ItemCount", 0),
        "size_bytes": table.get("TableSizeBytes", 0),
        "size_mb": round(table.get("TableSizeBytes", 0) / 1024 / 1024, 2),
        "billing_mode": table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
        "key_schema": [{"name": k["AttributeName"], "type": k["KeyType"]} for k in table["KeySchema"]],
        "attribute_definitions": [{"name": a["AttributeName"], "type": a["AttributeType"]} for a in table["AttributeDefinitions"]],
    }

    if "ProvisionedThroughput" in table:
        pt = table["ProvisionedThroughput"]
        result["provisioned_throughput"] = {
            "read_capacity_units": pt["ReadCapacityUnits"],
            "write_capacity_units": pt["WriteCapacityUnits"],
        }

    if "GlobalSecondaryIndexes" in table:
        result["gsis"] = [{
            "name": g["IndexName"],
            "status": g["IndexStatus"],
            "key_schema": [{"name": k["AttributeName"], "type": k["KeyType"]} for k in g["KeySchema"]],
            "item_count": g.get("ItemCount", 0),
        } for g in table["GlobalSecondaryIndexes"]]

    if table.get("TimeToLiveDescription"):
        result["ttl"] = table["TimeToLiveDescription"]

    return result


@tool
def get_table_metrics(table_name: str, period_minutes: int = 60) -> dict:
    """Get CloudWatch metrics for a DynamoDB table — consumed RCU/WCU, throttles (REAL DATA).

    Args:
        table_name: The DynamoDB table name.
        period_minutes: Lookback period in minutes.
    """
    _DEFAULT_BODY = {
        "metrics": [
            "ConsumedReadCapacityUnits",
            "ConsumedWriteCapacityUnits",
            "ReadThrottleEvents",
            "WriteThrottleEvents",
            "SuccessfulRequestLatency",
        ]
    }
    try:
        spec = registry.must_get("ddb_get_table_metrics")
        rendered = registry.render(spec.template_id, {})
        metrics_to_get = rendered.sql.get("metrics", _DEFAULT_BODY["metrics"])
    except KeyError:
        metrics_to_get = _DEFAULT_BODY["metrics"]

    cw = get_cloudwatch()
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=period_minutes)

    results = {}
    for metric_name in metrics_to_get:
        try:
            response = cw.get_metric_statistics(
                Namespace="AWS/DynamoDB",
                MetricName=metric_name,
                Dimensions=[{"Name": "TableName", "Value": table_name}],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=["Sum", "Average", "Maximum"],
            )
            datapoints = sorted(response["Datapoints"], key=lambda x: x["Timestamp"])
            if datapoints:
                results[metric_name] = {
                    "average": round(datapoints[-1].get("Average", 0), 2),
                    "maximum": round(datapoints[-1].get("Maximum", 0), 2),
                    "sum": round(datapoints[-1].get("Sum", 0), 2),
                    "datapoints_count": len(datapoints),
                }
            else:
                results[metric_name] = {"note": "No data in period"}
        except Exception as e:
            results[metric_name] = {"error": str(e)}

    return {"table_name": table_name, "period_minutes": period_minutes, "metrics": results}


@tool
def scan_sample_items(table_name: str, limit: int = 5, attributes: str = "") -> dict:
    """Scan a few sample items from the table to understand the data shape (REAL DATA).

    Data handling: this returns **live item content**. If the table holds
    personal data, that data enters the agent's context and the operator's
    transcript, both of which are governed differently from the table itself.
    Prefer :func:`describe_table` when only the schema is needed, and pass
    ``attributes`` to retrieve just the fields in question. Run this against
    tables containing regulated data (PHI, cardholder data, or personal data
    under GDPR) only where your own controls permit it.

    When ``attributes`` is omitted and a returned attribute name looks like
    personal data, the response carries a ``data_warning`` naming those fields.
    The fields are still returned: withholding them silently would leave the
    operator believing the table does not hold them. The check is a name-based
    heuristic, so treat it as a prompt to look rather than a classification.

    Args:
        table_name: The DynamoDB table name.
        limit: Max items to return.
        attributes: Optional comma-separated attribute names to return, for
            example ``"pk,sk,status"``. Omit to return whole items.
    """
    client = get_dynamodb()
    response = client.scan(TableName=table_name, Limit=limit, **_projection(attributes))
    items = response.get("Items", [])
    # Simplify DynamoDB format
    simplified = []
    for item in items:
        simple = {}
        for key, val in item.items():
            for type_key, type_val in val.items():
                simple[key] = type_val
        simplified.append(simple)
    return {
        "table_name": table_name,
        "items": simplified,
        "count": len(simplified),
        "scanned_count": response.get("ScannedCount", 0),
        # Names the personal-looking fields that were returned, when the caller
        # did not narrow the read. Advisory only — see _data_warning.
        **_data_warning(simplified, attributes),
    }


@tool
def get_table_ttl(table_name: str) -> dict:
    """Check TTL configuration for a table (REAL DATA).

    Args:
        table_name: The DynamoDB table name.
    """
    client = get_dynamodb()
    response = client.describe_time_to_live(TableName=table_name)
    return {"table_name": table_name, "ttl": response.get("TimeToLiveDescription", {})}


@tool
def list_backups(table_name: str) -> dict:
    """List existing backups for a table (REAL DATA).

    Args:
        table_name: The DynamoDB table name.
    """
    client = get_dynamodb()
    response = client.list_backups(TableName=table_name)
    backups = [{
        "name": b["BackupName"],
        "status": b["BackupStatus"],
        "created": b["BackupCreationDateTime"].isoformat(),
        "size_bytes": b.get("BackupSizeBytes", 0),
    } for b in response.get("BackupSummaries", [])]
    return {"table_name": table_name, "backups": backups, "count": len(backups)}


@tool
def create_backup(table_name: str, backup_name: str = "") -> dict:
    """Create an on-demand backup for a DynamoDB table. REQUIRES APPROVAL.

    Args:
        table_name: Table to backup.
        backup_name: Optional backup name.
    """
    client = get_dynamodb()
    if not backup_name:
        backup_name = f"{table_name}-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    response = client.create_backup(TableName=table_name, BackupName=backup_name)
    details = response.get("BackupDetails", {})
    return {
        "status": "success",
        "backup_name": details.get("BackupName"),
        "backup_arn": details.get("BackupArn"),
        "backup_status": details.get("BackupStatus"),
    }


@tool
def get_throttled_requests(table_name: str, period_minutes: int = 60) -> dict:
    """Check read/write throttled requests for a DynamoDB table.

    Args:
        table_name: Table name.
        period_minutes: Lookback period.
    """
    _DEFAULT_BODY = {"metrics": ["ReadThrottleEvents", "WriteThrottleEvents"]}
    try:
        spec = registry.must_get("ddb_get_throttled_requests")
        rendered = registry.render(spec.template_id, {})
        metric_list = rendered.sql.get("metrics", _DEFAULT_BODY["metrics"])
    except KeyError:
        metric_list = _DEFAULT_BODY["metrics"]

    cw = get_cloudwatch()
    from datetime import timedelta
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=period_minutes)
    results = {}
    for metric in metric_list:
        resp = cw.get_metric_statistics(
            Namespace="AWS/DynamoDB", MetricName=metric,
            Dimensions=[{"Name": "TableName", "Value": table_name}],
            StartTime=start, EndTime=end, Period=300, Statistics=["Sum"],
        )
        dps = sorted(resp["Datapoints"], key=lambda x: x["Timestamp"])
        total = sum(dp.get("Sum", 0) for dp in dps)
        results[metric] = {"total": int(total), "datapoints": len(dps)}
    return {"table_name": table_name, "throttling": results, "has_throttling": results["ReadThrottleEvents"]["total"] + results["WriteThrottleEvents"]["total"] > 0}


@tool
def get_gsi_status(table_name: str) -> dict:
    """Check GSI backpressure and status for a DynamoDB table.

    Args:
        table_name: Table name.
    """
    client = get_dynamodb()
    response = client.describe_table(TableName=table_name)
    table = response["Table"]
    gsis = []
    for gsi in table.get("GlobalSecondaryIndexes", []):
        gsis.append({
            "name": gsi["IndexName"],
            "status": gsi["IndexStatus"],
            "item_count": gsi.get("ItemCount", 0),
            "size_bytes": gsi.get("IndexSizeBytes", 0),
            "backfilling": gsi.get("Backfilling", False),
        })
    return {"table_name": table_name, "gsis": gsis, "count": len(gsis)}


@tool
def modify_capacity(table_name: str, read_units: int, write_units: int) -> dict:
    """Modify provisioned capacity (RCU/WCU) for a DynamoDB table. REQUIRES APPROVAL.

    Args:
        table_name: Table to modify.
        read_units: New read capacity units.
        write_units: New write capacity units.
    """
    client = get_dynamodb()
    try:
        client.update_table(
            TableName=table_name,
            ProvisionedThroughput={"ReadCapacityUnits": read_units, "WriteCapacityUnits": write_units},
        )
        return {"status": "updating", "table": table_name, "new_rcu": read_units, "new_wcu": write_units}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def switch_billing_mode(table_name: str, mode: str = "PAY_PER_REQUEST") -> dict:
    """Switch a DynamoDB table between on-demand and provisioned billing. REQUIRES APPROVAL.

    Args:
        table_name: Table to modify.
        mode: 'PAY_PER_REQUEST' (on-demand) or 'PROVISIONED'.
    """
    client = get_dynamodb()
    try:
        params = {"TableName": table_name, "BillingMode": mode}
        if mode == "PROVISIONED":
            params["ProvisionedThroughput"] = {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
        client.update_table(**params)
        return {"status": "updating", "table": table_name, "new_mode": mode}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def load_items_from_s3(table_name: str, s3_uri: str) -> dict:
    """Load items from an S3 file (JSON/CSV) into a DynamoDB table using batch writes. REQUIRES APPROVAL.

    Args:
        table_name: Target DynamoDB table.
        s3_uri: S3 URI of the file.
    """
    import boto3 as boto3_mod
    import csv
    import io
    import json as json_mod

    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket, key = parts[0], parts[1]

    # Encryption is already covered on both legs and needs no extra parameters:
    # in transit, boto3 talks to S3 over HTTPS by default; at rest, every object
    # is encrypted with SSE-S3 (AES-256) unless the bucket specifies a different
    # key, which S3 has applied to new objects by default since January 2023.
    # GetObject decrypts transparently for a caller with permission on the
    # object and, for SSE-KMS buckets, on the key. To *require* a particular
    # scheme rather than accept the default, enforce it on the bucket with a
    # policy condition on s3:x-amz-server-side-encryption.
    s3 = boto3_mod.client("s3", region_name=REGION)
    content = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")

    if key.endswith(".json"):
        items = json_mod.loads(content)
        if not isinstance(items, list):
            items = items.get("Items", items.get("items", [items]))
    else:
        reader = csv.DictReader(io.StringIO(content))
        items = [dict(row) for row in reader]

    client = get_dynamodb()
    written = 0
    # Batch write in chunks of 25
    for i in range(0, len(items), 25):
        batch = items[i:i+25]
        put_requests = []
        for item in batch:
            ddb_item = {}
            for k, v in item.items():
                if isinstance(v, (int, float)):
                    ddb_item[k] = {"N": str(v)}
                else:
                    ddb_item[k] = {"S": str(v)}
            put_requests.append({"PutRequest": {"Item": ddb_item}})
        try:
            client.batch_write_item(RequestItems={table_name: put_requests})
            written += len(put_requests)
        except Exception as e:
            return {"status": "partial", "rows_written": written, "error": str(e)}

    return {"status": "success", "table": table_name, "s3_uri": s3_uri, "items_loaded": written}


import re as _re

# Allowlist of sort-key operators accepted by query_table. Anything outside this
# set is rejected so attacker-supplied text can never reach the expression string.
_SORT_KEY_OPERATORS = {"=", "<", "<=", ">", ">=", "begins_with"}
# DynamoDB attribute-name charset. Rejects spaces, parentheses, operators, colons,
# and any other expression syntax an attacker might try to inject.
_ATTR_NAME_RE = _re.compile(r"^[A-Za-z0-9_.-]{1,255}$")


def _projection(attributes: str) -> dict:
    """Build a DynamoDB ProjectionExpression from a comma-separated attribute list.

    Lets a caller retrieve only the attributes they need, so a table holding
    personal data does not have to be read in full to answer a question about
    its shape or capacity. Returns ``{}`` when no attributes are given, which
    means "return the whole item".

    Every name goes through ``ExpressionAttributeNames`` placeholders, so a
    reserved word is handled correctly and nothing caller-supplied is
    concatenated into the expression.

    Raises:
        ValueError: An attribute name is outside the DynamoDB charset.
    """
    names = [a.strip() for a in (attributes or "").split(",") if a.strip()]
    if not names:
        return {}
    expression_names = {}
    placeholders = []
    for index, name in enumerate(names):
        if not _ATTR_NAME_RE.match(name):
            raise ValueError(
                f"Invalid attribute name {name!r}; must match ^[A-Za-z0-9_.-]{{1,255}}$"
            )
        placeholder = f"#p{index}"
        expression_names[placeholder] = name
        placeholders.append(placeholder)
    return {
        "ProjectionExpression": ", ".join(placeholders),
        "ExpressionAttributeNames": expression_names,
    }


# Attribute-name fragments that commonly denote personal data. Used only to warn
# the operator, never to filter: silently withholding a field would leave them
# believing the table does not hold it, which is worse than returning it with a
# caveat. This is a name-based heuristic and is neither exhaustive nor
# authoritative — an attribute called `ref_2` can hold a national identifier just
# as easily as one called `ssn`.
_PII_HINT_FRAGMENTS = (
    "email", "mail", "phone", "mobile", "telephone",
    "ssn", "social_security", "national_id", "nino", "passport",
    "licence", "license", "dob", "birth",
    "address", "postcode", "postal", "zip",
    "iban", "account_number", "sort_code", "card", "cvv",
    "salary", "tax",
    "patient", "mrn", "diagnosis",
    "first_name", "last_name", "surname", "full_name", "fullname",
)

# Values shaped like direct identifiers, for checking key values specifically.
_EMAIL_SHAPED = _re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_PHONE_SHAPED = _re.compile(r"\+?\d[\d\s().-]{7,}\d")


def _pii_hint_fields(items: list) -> list:
    """Return attribute names present in ``items`` that look like personal data."""
    hits = set()
    for item in items:
        for name in item:
            lowered = name.lower()
            if any(fragment in lowered for fragment in _PII_HINT_FRAGMENTS):
                hits.add(name)
    return sorted(hits)


def _data_warning(items: list, attributes: str) -> dict:
    """Return a warning about whole-item reads that look like personal data.

    Empty when the caller narrowed the read with ``attributes``, because they
    have then already chosen which fields to see, and empty when no attribute
    name looks personal.
    """
    if (attributes or "").strip():
        return {}
    fields = _pii_hint_fields(items)
    if not fields:
        return {}
    return {
        "data_warning": (
            "Whole items were returned, and these attribute names suggest personal "
            f"data: {', '.join(fields)}. That content is now in the agent context "
            "and the operator transcript, which are governed separately from the "
            'table itself. Pass attributes="pk,sk,..." to narrow future reads to '
            "the fields you actually need. This is a name-based heuristic, so read "
            "it as a prompt to check rather than as a data classification."
        ),
        "data_warning_fields": fields,
    }


def _key_shape_warning(item_keys: dict) -> dict:
    """Warn when a key value looks like a direct identifier.

    Key values are echoed back to the caller and therefore land in the
    transcript and the audit trail, both of which are retained for longer than
    the item may be. Warns rather than refuses: a value that matches these
    shapes can still be a legitimate key, and refusing would block a valid
    write on the strength of a regular expression.
    """
    flagged = []
    for name, value in item_keys.items():
        if not isinstance(value, str):
            continue
        if _EMAIL_SHAPED.search(value):
            flagged.append(f"{name} looks like an email address")
        elif _PHONE_SHAPED.search(value):
            flagged.append(f"{name} looks like a phone number")
    if not flagged:
        return {}
    return {
        "key_warning": (
            f"{'; '.join(flagged)}. Key values are echoed in this response and so "
            "are recorded in the transcript and audit trail. Prefer an opaque "
            "identifier such as USER#<uuid> and hold the identifying value in a "
            "non-key attribute, which is not echoed back."
        ),
    }


@tool
def query_table(
    table_name: str,
    partition_key_value: str,
    sort_key_name: str = None,
    sort_key_operator: str = None,
    sort_key_value: str = None,
    attributes: str = "",
) -> dict:
    """Query a DynamoDB table by partition key with an optional structured sort key condition.

    The sort key condition is built from allowlisted, structured parameters instead
    of a free-form expression string. The attribute name is validated against the
    DynamoDB attribute-name charset and passed via ExpressionAttributeNames, the
    operator is validated against a fixed allowlist, and the value is bound safely
    as an ExpressionAttributeValues placeholder. Nothing user-supplied is ever
    concatenated into the KeyConditionExpression, preventing NoSQL injection.

    Data handling: matched items are returned in full unless ``attributes``
    narrows them, so a table holding personal data will surface that data into
    the agent's context and the operator's transcript. Name the attributes you
    need rather than reading whole items, and treat regulated data (PHI,
    cardholder data, or personal data under GDPR) as subject to your own
    controls — see the AWS shared responsibility model.

    When ``attributes`` is omitted and a returned attribute name looks like
    personal data, the response carries a ``data_warning`` naming those fields.
    The fields are still returned: withholding them silently would leave the
    operator believing the table does not hold them. The check is a name-based
    heuristic, so treat it as a prompt to look rather than a classification.

    Args:
        table_name: Table to query.
        partition_key_value: Value for the partition key (pk).
        sort_key_name: Optional sort key attribute name (e.g., "sk"). Must match
            ^[A-Za-z0-9_.-]{1,255}$.
        sort_key_operator: Optional comparison operator. One of
            "=", "<", "<=", ">", ">=", or "begins_with".
        sort_key_value: Optional sort key value bound safely as an attribute value.
        attributes: Optional comma-separated attribute names to return, for
            example ``"pk,sk,status"``. Omit to return whole items.
    """
    client = get_dynamodb()

    # Partition key condition uses placeholders only.
    key_condition = "#pk = :pk"
    expr_attr_names = {"#pk": "pk"}
    expr_attr_values = {":pk": {"S": partition_key_value}}

    # Only apply a sort key condition when the operator and value are provided.
    if sort_key_operator is not None or sort_key_value is not None:
        if not sort_key_name:
            return {"status": "failed", "error": "sort_key_name is required when a sort key condition is provided"}
        if sort_key_operator not in _SORT_KEY_OPERATORS:
            raise ValueError(
                f"Invalid sort_key_operator {sort_key_operator!r}; "
                f"must be one of {sorted(_SORT_KEY_OPERATORS)}"
            )
        if sort_key_value is None:
            return {"status": "failed", "error": "sort_key_value is required when sort_key_operator is provided"}
        if not _ATTR_NAME_RE.match(sort_key_name):
            raise ValueError(
                f"Invalid sort_key_name {sort_key_name!r}; must match ^[A-Za-z0-9_.-]{{1,255}}$"
            )

        expr_attr_names["#sk"] = sort_key_name
        expr_attr_values[":sk"] = {"S": sort_key_value}
        if sort_key_operator == "begins_with":
            key_condition += " AND begins_with(#sk, :sk)"
        else:
            key_condition += f" AND #sk {sort_key_operator} :sk"

    # A projection reuses ExpressionAttributeNames, so combine the two maps: the
    # #pk / #sk placeholders have to survive alongside the #p0.. projection ones.
    projection = _projection(attributes)
    all_attr_names = {
        **expr_attr_names,
        **projection.get("ExpressionAttributeNames", {}),
    }

    params = {
        "TableName": table_name,
        "KeyConditionExpression": key_condition,
        "ExpressionAttributeNames": all_attr_names,
        "ExpressionAttributeValues": expr_attr_values,
        "Limit": 20,
    }
    if "ProjectionExpression" in projection:
        params["ProjectionExpression"] = projection["ProjectionExpression"]
    try:
        response = client.query(**params)
        items = response.get("Items", [])
        simplified = []
        for item in items:
            simple = {k: list(v.values())[0] for k, v in item.items()}
            simplified.append(simple)
        return {
            "table": table_name,
            "items": simplified,
            "count": len(simplified),
            "scanned": response.get("ScannedCount", 0),
            # Names the personal-looking fields that were returned, when the
            # caller did not narrow the read. Advisory only — see _data_warning.
            **_data_warning(simplified, attributes),
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def put_item(table_name: str, item_json: str) -> dict:
    """Put (insert/replace) an item into a DynamoDB table. REQUIRES APPROVAL.

    Data handling: the success response echoes the item's ``pk`` and ``sk`` so the
    operator can confirm what was written, and those keys are therefore recorded
    in the transcript and the audit trail. Key values should not embed personal
    data for that reason — a single-table design is better served by an opaque
    identifier (``USER#<uuid>``) than by a direct identifier such as an email
    address or a phone number. Non-key attributes are not echoed back.

    If a key value looks like an email address or a phone number, the response
    carries a ``key_warning``. The write still succeeds: a value matching those
    shapes can be a legitimate key, so this is feedback on key design rather
    than a rejection.

    Args:
        table_name: Target table.
        item_json: JSON string of the item (e.g., '{"pk": "USER#<uuid>", "sk": "PROFILE", "name": "..."}').
    """
    import json as json_mod
    client = get_dynamodb()
    item_dict = json_mod.loads(item_json)
    # Convert to DynamoDB format
    ddb_item = {}
    for k, v in item_dict.items():
        if isinstance(v, str):
            ddb_item[k] = {"S": v}
        elif isinstance(v, (int, float)):
            ddb_item[k] = {"N": str(v)}
        elif isinstance(v, bool):
            ddb_item[k] = {"BOOL": v}
        else:
            ddb_item[k] = {"S": str(v)}
    try:
        client.put_item(TableName=table_name, Item=ddb_item)
        echoed_keys = {k: v for k, v in item_dict.items() if k in ("pk", "sk")}
        return {
            "status": "success",
            "table": table_name,
            "item_keys": echoed_keys,
            # Flags a key value that looks like a direct identifier. The write
            # already succeeded — this is feedback on the key design, not a
            # rejection. See _key_shape_warning for why it does not refuse.
            **_key_shape_warning(echoed_keys),
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def batch_write_items(table_name: str, items_json: str) -> dict:
    """Batch write up to 25 items to a DynamoDB table. REQUIRES APPROVAL.

    Args:
        table_name: Target table.
        items_json: JSON array of items to insert.
    """
    import json as json_mod
    client = get_dynamodb()
    items = json_mod.loads(items_json)
    put_requests = []
    for item in items[:25]:
        ddb_item = {}
        for k, v in item.items():
            if isinstance(v, str):
                ddb_item[k] = {"S": v}
            elif isinstance(v, (int, float)):
                ddb_item[k] = {"N": str(v)}
            else:
                ddb_item[k] = {"S": str(v)}
        put_requests.append({"PutRequest": {"Item": ddb_item}})
    try:
        client.batch_write_item(RequestItems={table_name: put_requests})
        return {"status": "success", "table": table_name, "items_written": len(put_requests)}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def add_gsi(table_name: str, index_name: str, partition_key: str, sort_key: str = "") -> dict:
    """Add a Global Secondary Index to a DynamoDB table. REQUIRES APPROVAL.

    Args:
        table_name: Table to add GSI to.
        index_name: Name for the new GSI.
        partition_key: Partition key attribute for the GSI.
        sort_key: Optional sort key attribute.
    """
    client = get_dynamodb()
    key_schema = [{"AttributeName": partition_key, "KeyType": "HASH"}]
    attr_defs = [{"AttributeName": partition_key, "AttributeType": "S"}]
    if sort_key:
        key_schema.append({"AttributeName": sort_key, "KeyType": "RANGE"})
        attr_defs.append({"AttributeName": sort_key, "AttributeType": "S"})
    try:
        client.update_table(
            TableName=table_name,
            AttributeDefinitions=attr_defs,
            GlobalSecondaryIndexUpdates=[{
                "Create": {
                    "IndexName": index_name,
                    "KeySchema": key_schema,
                    "Projection": {"ProjectionType": "ALL"},
                }
            }],
        )
        return {"status": "creating", "table": table_name, "gsi": index_name, "partition_key": partition_key, "sort_key": sort_key or "none"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def export_table_to_s3(table_arn: str, s3_bucket: str, s3_prefix: str = "dynamodb-exports") -> dict:
    """Export a DynamoDB table to S3 for data sharing or analytics. REQUIRES APPROVAL.

    Args:
        table_arn: ARN of the DynamoDB table to export.
        s3_bucket: S3 bucket to export to.
        s3_prefix: S3 prefix/folder for the export.
    """
    client = get_dynamodb()
    try:
        response = client.export_table_to_point_in_time(
            TableArn=table_arn,
            S3Bucket=s3_bucket,
            S3Prefix=s3_prefix,
            ExportFormat="DYNAMODB_JSON",
        )
        export_desc = response.get("ExportDescription", {})
        return {
            "status": "initiated",
            "export_arn": export_desc.get("ExportArn"),
            "export_status": export_desc.get("ExportStatus"),
            "s3_location": f"s3://{s3_bucket}/{s3_prefix}",
            "format": "DYNAMODB_JSON",
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@tool
def clone_table_structure(source_table_name: str, target_table_name: str) -> dict:
    """Clone a DynamoDB table structure (schema only, no data) to create a lower-env copy. REQUIRES APPROVAL.

    Args:
        source_table_name: Source table to clone structure from.
        target_table_name: Name for the new table.
    """
    client = get_dynamodb()
    try:
        # Describe source
        source = client.describe_table(TableName=source_table_name)["Table"]

        # Build create params from source
        create_params = {
            "TableName": target_table_name,
            "KeySchema": source["KeySchema"],
            "AttributeDefinitions": source["AttributeDefinitions"],
            "BillingMode": "PAY_PER_REQUEST",
        }

        # Copy GSIs if any
        if "GlobalSecondaryIndexes" in source:
            create_params["GlobalSecondaryIndexes"] = [{
                "IndexName": gsi["IndexName"],
                "KeySchema": gsi["KeySchema"],
                "Projection": gsi["Projection"],
            } for gsi in source["GlobalSecondaryIndexes"]]

        client.create_table(**create_params)
        return {
            "status": "creating",
            "source_table": source_table_name,
            "target_table": target_table_name,
            "keys_cloned": source["KeySchema"],
            "gsis_cloned": len(source.get("GlobalSecondaryIndexes", [])),
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@app.entrypoint
def invoke(payload, context=None):
    prompt = payload.get("prompt", "")
    user_id = payload.get("user_id", "anonymous")
    if not prompt:
        return {"error": "Missing 'prompt' in payload"}

    # Programmatic Tier-3 gate. Operator decisions arrive in the payload from
    # the calling application, never from model output, and each is bound to a
    # single tool + argument fingerprint.
    tier3 = Tier3ApprovalHook(approvals=payload.get("approvals"), user_id=user_id)

    agent = Agent(
        system_prompt=SYSTEM_PROMPT,
        hooks=[tier3],
        tools=[list_tables, describe_table, get_table_metrics, scan_sample_items,
               get_table_ttl, list_backups, create_backup,
               get_throttled_requests, get_gsi_status, modify_capacity, switch_billing_mode,
               load_items_from_s3, query_table, put_item, batch_write_items, add_gsi,
               export_table_to_s3, clone_table_structure],
    )
    result = agent(prompt)

    # A Tier-3 operation was proposed but is not yet approved. The agent loop
    # stopped before the tool ran; return the pending request for the operator
    # to confirm. Nothing has been executed against the table.
    if getattr(result, "stop_reason", None) == "interrupt":
        return {
            "response": None,
            "awaiting_approval": True,
            "pending_approvals": pending_approvals(result),
            "user_id": user_id,
            "agent_name": "DynamoDB Ops Agent (LIVE)",
            "agent_avatar": "⚡",
        }

    return {"response": result.message, "user_id": user_id, "agent_name": "DynamoDB Ops Agent (LIVE)", "agent_avatar": "⚡"}


if __name__ == "__main__":
    app.run()
