# Sales Call Classification API

Serverless ingestion endpoint: HappyRobot workflow → API Gateway → Lambda → DynamoDB.
Feeds a downstream dashboard (Dash/Plotly, deployed on Amazon ECS Express Mode).

## Architecture

```
HappyRobot workflow
      │  POST (x-api-key)
      ▼
API Gateway ──▶ Lambda (ingest) ──▶ DynamoDB (sales-call-classifications)
                                          │
                                          ▼
                          Dash/Plotly dashboard (ECS Express Mode)
                          — reads the table directly via boto3
```

The ingestion side (this README) and the dashboard are separate deployable
projects that share one DynamoDB table. See the dashboard project's own
README for its deployment steps.

## Deploy

Requires the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) and configured AWS credentials.

```bash
sam build
sam deploy --guided
```

On first deploy, `--guided` will prompt for a stack name, region, and confirm IAM
role creation. It saves your answers to `samconfig.toml` so future deploys can
just be `sam deploy`.

After deploy, grab the outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name <your-stack-name> \
  --query "Stacks[0].Outputs"
```

This gives you:
- **ApiEndpoint** — the POST URL
- **ApiKeyId** — use this to fetch the actual key value:

```bash
aws apigateway get-api-key --api-key <ApiKeyId> --include-value --query "value" --output text
```

## Request format

```
POST {ApiEndpoint}
x-api-key: <your-api-key>
Content-Type: application/json

{
  "call_id": "optional-your-own-id",
  "classification": "qualified_lead",
  "agent_id": "agent-123",
  "booking_decision": "booked",
  "decline_reason": null,
  "mc_number": "123456",
  "reference_number": "REF-12345",
  "call_duration": 245,
  "metadata": {
    "any": "extra fields from the HappyRobot workflow extraction"
  }
}
```

`call_id` and `timestamp` are optional — if omitted, the Lambda generates a
UUID and uses the current UTC time. `booking_decision`, `decline_reason`,
`mc_number`, `reference_number`, and `call_duration` are all optional —
DynamoDB doesn't enforce a schema, so records that don't reach the
negotiation stage (e.g. `no_answer`, `not_interested`) simply omit the
fields that don't apply.

Response:

```json
{ "call_id": "...", "status": "stored" }
```

## Wiring into a HappyRobot workflow

In the workflow builder, add a webhook/HTTP request node as the terminal step
after your Classify/Extract nodes:

- **Method:** POST
- **URL:** the `ApiEndpoint` output above
- **Headers:** `x-api-key: <key>`, `Content-Type: application/json`
- **Body:** map the classification and extracted fields into the JSON shape
  above — put anything workflow-specific under `metadata` rather than adding
  new top-level fields, so the Lambda/table schema doesn't need to change
  every time the workflow does.

## Table design notes

- Partition key `call_id`, sort key `timestamp` — supports fetching a call's
  full history and natural chronological ordering.
- GSI `classification-timestamp-index` — lets the dashboard query "all calls
  of type X in the last N days" without a full table scan.
- A `booking-decision-timestamp-index` GSI (same pattern, keyed on
  `booking_decision` + `timestamp`) would let the dashboard query "all
  booked/declined calls in the last N days" the same way — not yet added
  to `template.yaml`, worth adding if the dashboard's current full-table
  scan becomes slow as data volume grows.
- Only attributes used as a table key or a GSI key need to be declared in
  `AttributeDefinitions` in `template.yaml`. Everything else
  (`decline_reason`, `mc_number`, `reference_number`, `call_duration`, and
  anything nested in `metadata`) is just regular item data — DynamoDB is
  schemaless for those, so new fields from workflow changes don't require
  touching the table definition. Add more GSIs the same way if the
  dashboard needs to filter by `agent_id` or another field directly.

## Security notes

- The API key gates who can call the endpoint at all; rate limiting is set
  conservatively (10 req/s, burst 20) — raise this in `template.yaml` if
  call volume needs it.
- Given you've had live keys leak into chat before — store this API key in
  HappyRobot's secrets/env config for the workflow, not hardcoded in the
  node body, and rotate it if it's ever pasted somewhere it shouldn't be.
- Lambda's IAM role is scoped to `PutItem`/CRUD only on this one table via
  `DynamoDBCrudPolicy` — it can't touch other tables in your account.
- The dashboard's ECS task role is scoped to read-only
  (`Scan`/`Query`/`GetItem`) on this same table and its GSIs — it can't
  write to or modify data, only display it.

## Local testing

```bash
sam local invoke IngestFunction --event events/test-event.json
```

(create `events/test-event.json` with an API Gateway proxy event shape if
you want to test without deploying)

## Generating dummy data

For testing the dashboard without waiting on real call volume, use
`generate_dummy_data.py` (lives alongside the dashboard project) to write
realistic records directly into the table via `boto3`:

```bash
python3 generate_dummy_data.py --dry-run                # preview only
python3 generate_dummy_data.py --count 500 --days 90 \
  --table sales-call-classifications --region us-east-1
```

It bakes in a few intentional patterns useful for testing the dashboard's
charts: booking rate improving from ~30% to ~60% over the date range,
weekday call volume ~3x weekend volume, and decline reasons spread evenly
across four categories. See the script's docstring for the full list of
tunable constants.

## Downstream dashboard

The Dash/Plotly dashboard that reads this table is deployed separately on
**Amazon ECS Express Mode** (App Runner's replacement as of April 2026).
It queries the table read-only via a scoped ECS task role — see the
dashboard project's own README for its full deployment steps (ECR, IAM
roles, Express Mode CLI commands, and troubleshooting notes).
