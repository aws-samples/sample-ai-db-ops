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

"""Seed dbops-orders DynamoDB table with a realistic order-stream workload."""
import boto3, random, string, time
from decimal import Decimal
from datetime import datetime, timedelta, timezone

REGION = "us-east-1"
TABLE = "dbops-orders"

ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE)

cw = boto3.client("dynamodb", region_name=REGION)
desc = cw.describe_table(TableName=TABLE)
print(f"table: {TABLE}, current items: {desc['Table'].get('ItemCount', 0)}")

print("seeding 1000 orders with hot partitions and a few VIP customers...")

statuses = ["placed", "paid", "shipped", "delivered", "cancelled", "refunded"]
hot_customers = [f"CUST-VIP-{i}" for i in range(5)]   # creates a hot-partition pattern
all_customers = hot_customers + [f"CUST-{random.randint(1, 200):04d}" for _ in range(200)]

with table.batch_writer() as batch:
    for i in range(1000):
        customer = random.choice(all_customers)
        order_date = (datetime.now(timezone.utc) - timedelta(hours=random.randint(0, 168))).isoformat()
        order_id = f"ORD-{i:06d}-{''.join(random.choices(string.ascii_uppercase+string.digits, k=4))}"

        batch.put_item(Item={
            "pk": f"ORDER#{order_id}",
            "sk": f"v0",
            "customer_id": customer,
            "order_date": order_date,
            "status": random.choice(statuses),
            "total_cents": Decimal(str(random.randint(500, 50000))),
            "item_count": random.randint(1, 8),
            "shipping_method": random.choice(["standard", "express", "overnight"]),
        })

        # add 1-3 line items per order (sk = ITEM#N) so range queries return data
        for j in range(random.randint(1, 3)):
            batch.put_item(Item={
                "pk": f"ORDER#{order_id}",
                "sk": f"ITEM#{j:02d}",
                "sku": f"SKU-{random.randint(1, 200):04d}",
                "quantity": random.randint(1, 5),
                "price_cents": Decimal(str(random.randint(100, 9999))),
            })

print("running 200 concentrated reads against VIP partition keys (hot-partition pattern)...")
for _ in range(200):
    custom = random.choice(hot_customers)
    # scan the GSI for this hot customer
    table.query(
        IndexName="gsi-customer-date",
        KeyConditionExpression="customer_id = :c",
        ExpressionAttributeValues={":c": custom},
        Limit=20,
    )

print("done — DDB has 1000 orders + line items, hot CUST-VIP-* keys for the contributor-insights demo")
