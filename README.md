# Sales Call Classification API

Serverless ingestion endpoint: HappyRobot workflow → API Gateway → Lambda → DynamoDB.
Feeds a downstream dashboard (e.g. Dash/Plotly on Fargate).

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
  "metadata": {
    "any": "extra fields from the HappyRobot workflow extraction"
  }
}
```

`call_id` and `timestamp` are optional — if omitted, the Lambda generates a
UUID and uses the current UTC time.

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
  of type X in the last N days" without a full table scan. Add more GSIs the
  same way if the dashboard needs to filter by `agent_id` etc.

## Security notes

- The API key gates who can call the endpoint at all; rate limiting is set
  conservatively (10 req/s, burst 20) — raise this in `template.yaml` if
  call volume needs it.
- Given you've had live keys leak into chat before — store this API key in
  HappyRobot's secrets/env config for the workflow, not hardcoded in the
  node body, and rotate it if it's ever pasted somewhere it shouldn't be.
- Lambda's IAM role is scoped to `PutItem`/CRUD only on this one table via
  `DynamoDBCrudPolicy` — it can't touch other tables in your account.

## Local testing

```bash
sam local invoke IngestFunction --event events/test-event.json
```

(create `events/test-event.json` with an API Gateway proxy event shape if
you want to test without deploying)
