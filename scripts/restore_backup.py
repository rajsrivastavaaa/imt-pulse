"""Restore content from a backup into a freshly deployed stack.

Usage (after ./deploy.sh, from the project folder):
  .venv/bin/python scripts/restore_backup.py backups/table-2026-10-22.json            # company schedule + past content
  .venv/bin/python scripts/restore_backup.py backups/table-2026-10-22.json --all      # also old profiles/scores/events

By default only the company schedule (SCHEDULE) and daily content (DAY#...) are restored. User profiles,
scores and events are keyed by Cognito user IDs, which change when the user pool is recreated, so they
are only useful for record-keeping. Everyone has to sign up again after a restart.
"""
import json
import sys

import boto3
from boto3.dynamodb.types import TypeDeserializer

STACK, REGION = "imt-pulse", "ap-southeast-2"

if len(sys.argv) < 2:
    sys.exit(__doc__)
restore_all = "--all" in sys.argv
items = json.load(open(sys.argv[1]))["Items"]

cfn = boto3.client("cloudformation", region_name=REGION)
outputs = {o["OutputKey"]: o["OutputValue"] for o in cfn.describe_stacks(StackName=STACK)["Stacks"][0]["Outputs"]}
table = boto3.resource("dynamodb", region_name=REGION).Table(outputs["TableName"])

des = TypeDeserializer()
n = 0
with table.batch_writer() as batch:
    for raw in items:
        item = {k: des.deserialize(v) for k, v in raw.items()}
        if restore_all or item["PK"] == "SCHEDULE" or item["PK"].startswith("DAY#"):
            batch.put_item(Item=item)
            n += 1
print(f"Restored {n} items into {outputs['TableName']}")
