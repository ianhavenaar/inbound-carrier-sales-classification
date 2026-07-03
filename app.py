import json
import os
import uuid
from datetime import datetime, timezone

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

REQUIRED_FIELDS = ["classification"]


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    missing = [f for f in REQUIRED_FIELDS if f not in body]
    if missing:
        return _response(400, {"error": f"Missing required fields: {missing}"})

    item = {
        "call_id": body.get("call_id", str(uuid.uuid4())),
        "timestamp": body.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "classification": body["classification"],
        "agent_id": body.get("agent_id", "unknown"),
        # HappyRobot workflows often carry structured extraction output —
        # store it as-is under metadata so schema changes upstream don't
        # require a Lambda redeploy.
        "metadata": body.get("metadata", {}),
    }

    try:
        table.put_item(Item=item)
    except Exception as e:
        # Don't leak internal error details to the caller
        print(f"DynamoDB write failed: {e}")
        return _response(500, {"error": "Failed to store record"})

    return _response(201, {"call_id": item["call_id"], "status": "stored"})


def _response(status_code, body_dict):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body_dict),
    }
