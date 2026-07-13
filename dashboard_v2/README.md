# Deploying the Dashboard to Amazon ECS Express Mode

This deploys the Dash app in `app.py` as a container on **ECS Express Mode**
(App Runner's replacement — App Runner stopped accepting new customers
April 30, 2026). Express Mode provisions a Fargate service, Application
Load Balancer, HTTPS, auto scaling, and a public URL from a single command.

Deployed service in this project: **carrier-sales-call-dashboard**
AWS Account: `331339687011` | Region: `us-east-1`

---

## 1. Project files

```
dashboard/
├── app.py
├── requirements.txt
├── Dockerfile
├── ecs-task-trust-policy.json
├── ecs-infrastructure-trust-policy.json
├── permissions-policy.json
└── README.md
```

---

## 2. Create the ECR repository

```bash
aws ecr create-repository --repository-name carrier-sales-call-dashboard --region us-east-1
```

Confirm it exists:
```bash
aws ecr describe-repositories --repository-names carrier-sales-call-dashboard --region us-east-1
```

---

## 3. Build and push the image

```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 331339687011.dkr.ecr.us-east-1.amazonaws.com

# Build
docker build -t carrier-sales-call-dashboard .

# Tag
docker tag carrier-sales-call-dashboard:latest 331339687011.dkr.ecr.us-east-1.amazonaws.com/carrier-sales-call-dashboard:latest

# Push
docker push 331339687011.dkr.ecr.us-east-1.amazonaws.com/carrier-sales-call-dashboard:latest
```

---

## 4. Create the three required IAM roles

Express Mode needs three roles: an **execution role** (pulls the image,
writes logs), an **infrastructure role** (lets Express Mode manage the
ALB/networking on your behalf), and a **task role** (lets your running
container call DynamoDB).

```bash
# Execution role
aws iam create-role --role-name ecsTaskExecutionRole \
  --assume-role-policy-document file://ecs-task-trust-policy.json
aws iam attach-role-policy --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Infrastructure role
aws iam create-role --role-name ecsInfrastructureRoleForExpressServices \
  --assume-role-policy-document file://ecs-infrastructure-trust-policy.json
aws iam attach-role-policy --role-name ecsInfrastructureRoleForExpressServices \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices

# Task role — DynamoDB read access for the dashboard
aws iam create-role --role-name dashboard-ecs-task-role \
  --assume-role-policy-document file://ecs-task-trust-policy.json
aws iam put-role-policy --role-name dashboard-ecs-task-role \
  --policy-name dashboard-dynamodb-read \
  --policy-document file://permissions-policy.json
```

---

## 5. VPC check

Express Mode needs a default VPC with public subnets. If you hit
`InvalidParameterException: No default VPC or subnets found`, recreate one:

```bash
aws ec2 create-default-vpc --region us-east-1
aws ec2 describe-subnets --filters "Name=default-for-az,Values=true" --region us-east-1
```

If `create-default-vpc` fails (some accounts can't recreate one), you'll
need to build a minimal VPC manually and pass `--network-configuration`
with explicit subnet IDs to the deploy command in step 6 — ask if you hit
this case.

---

## 6. Deploy the Express Mode service

```bash
aws ecs create-express-gateway-service \
  --service-name carrier-sales-call-dashboard \
  --execution-role-arn arn:aws:iam::331339687011:role/ecsTaskExecutionRole \
  --infrastructure-role-arn arn:aws:iam::331339687011:role/ecsInfrastructureRoleForExpressServices \
  --task-role-arn arn:aws:iam::331339687011:role/dashboard-ecs-task-role \
  --primary-container '{
    "image": "331339687011.dkr.ecr.us-east-1.amazonaws.com/carrier-sales-call-dashboard:latest",
    "containerPort": 8080,
    "environment": [
      {"name": "TABLE_NAME", "value": "sales-call-classifications"},
      {"name": "AWS_REGION", "value": "us-east-1"}
    ]
  }' \
  --health-check-path "/" \
  --cpu 256 \
  --memory 512 \
  --scaling-target '{"minTaskCount": 1, "maxTaskCount": 2, "autoScalingMetric": "AVERAGE_CPU", "autoScalingTargetValue": 60}' \
  --region us-east-1 \
  --monitor-resources
```

`--monitor-resources` streams live provisioning status until the service
is up. This takes a few minutes (ALB creation is usually the slowest part).

---

## 7. Get your service ARN and public URL

If you didn't note the ARN from step 6's output:
```bash
aws ecs list-services --cluster default --region us-east-1
```

Then get full details, including the public endpoint:
```bash
aws ecs describe-express-gateway-service \
  --service-arn arn:aws:ecs:us-east-1:331339687011:service/default/carrier-sales-call-dashboard \
  --region us-east-1
```

Look under `service.activeConfigurations[0].ingressPaths[0].endpoint` in
the JSON output — that's your dashboard URL, e.g.:
```
https://ca-647a3b36dac94a54a80f790196ea7095.ecs.us-east-1.on.aws
```

To check status quickly without the full JSON dump:
```bash
aws ecs describe-express-gateway-service \
  --service-arn arn:aws:ecs:us-east-1:331339687011:service/default/carrier-sales-call-dashboard \
  --region us-east-1 \
  --query 'service.status'
```

---

## 8. Populate the table with dummy data

```bash
cd ~/scripts   # wherever generate_dummy_data.py lives
python3 generate_dummy_data.py --count 500 --days 90 \
  --table sales-call-classifications --region us-east-1
```

Refresh the dashboard URL — it auto-refreshes every 60 seconds via
`dcc.Interval`, or just reload the page.

---

## 9. Redeploying after code changes

Whenever `app.py` changes:

```bash
docker build -t carrier-sales-call-dashboard .
docker tag carrier-sales-call-dashboard:latest 331339687011.dkr.ecr.us-east-1.amazonaws.com/carrier-sales-call-dashboard:latest
docker push 331339687011.dkr.ecr.us-east-1.amazonaws.com/carrier-sales-call-dashboard:latest
```

Then trigger a new deployment with the updated image:
```bash
aws ecs update-express-gateway-service \
  --service-arn arn:aws:ecs:us-east-1:331339687011:service/default/carrier-sales-call-dashboard \
  --primary-container '{
    "image": "331339687011.dkr.ecr.us-east-1.amazonaws.com/carrier-sales-call-dashboard:latest",
    "containerPort": 8080
  }' \
  --region us-east-1 \
  --monitor-resources
```
