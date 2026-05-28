# W7 Evidence Pack

## Cover

- Team/app: StudyBot / EduBot
- Public frontend: `https://nguyenductien.cloud`
- Public API: `https://api.nguyenductien.cloud`
- Branch: `planner-clarification-main`
- Commit at evidence creation: `a4bce0f48f89a0cb16e0233f5c2dc8a6a5882506`
- Demo credentials: use `demo@studybot.com` in the sign-in screen, or query `?user=demo` for local testing.

## Architecture

See [architecture.md](architecture.md). Core choices:

- Frontend hosting: S3 private bucket behind CloudFront.
- API: API Gateway HTTP API with Lambda integrations.
- Compute: Python 3.12 Lambdas for auth, sessions, upload, documents, ingestion, Q&A, summary, quiz/flashcards, planner, history/dashboard.
- Database: DynamoDB table `StudyBotDocuments`, partitioned by user id.
- Object storage: S3 bucket `studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk`.
- Vector/RAG: Bedrock Knowledge Base `LI32IWLOB5`, data source `V0ISBKEMXT`, S3 Vectors index `studybot-kb-index`.
- Identity: lightweight app identity via email/user id and `X-User-Id` header for the W7 demo.
- Network: isolated VPC subnets and VPC endpoints for S3, DynamoDB, Bedrock, Bedrock Agent Runtime, Bedrock Agent, and Textract.
- IaC: CDK stack `StudyBotInfraStack` plus SAM template for backend compatibility.
- Observability: CloudWatch dashboard `StudyBot-W7-Operations`, alarms, and Lambda/API logs.

## Deployment Proof

- CDK stack: `StudyBotInfraStack` in `ap-southeast-1`.
- API domain output: `ApiCustomDomain=api.nguyenductien.cloud`.
- Frontend domain output: `FrontendCustomDomain=nguyenductien.cloud`.
- API output: `HttpApiUrl=https://3sgavxe4c0.execute-api.ap-southeast-1.amazonaws.com`.
- Frontend CloudFront output: `d202pyjoa7b4uh.cloudfront.net`.
- VPC output: `vpc-06d2de3b6e14576ca`.
- Key output names: `UploadsBucketName`, `DocumentsTableName`, `KnowledgeBaseId`, `DataSourceId`, `VectorIndexArn`, `OperationsDashboardName`.
- Deploy command used: `cd infra; cdk deploy StudyBotInfraStack --require-approval never --outputs-file outputs.json`.
- Deployed outputs are saved at `infra/outputs.json`.

## Security

- IAM is scoped by function role: read-only history/dashboard access, DynamoDB writes only where needed, S3 put only for uploads, S3 get only for processed text, Bedrock retrieve/invoke only for AI functions.
- S3 frontend bucket blocks public access; CloudFront is the public entry point.
- Upload bucket access is through presigned upload or Lambda-controlled paths under `raw/` and processed paths under `processed/`.
- DynamoDB user/session isolation uses `PK=USER#{user_id}` and per-item `session_id`; endpoints filter by active user/session.
- CORS allows `*` for hackathon/demo accessibility. Production should restrict this to the CloudFront domain.
- Lambdas run in private isolated subnets with gateway/interface VPC endpoints, avoiding public NAT for AWS service calls.
- Bedrock KB role includes permission for processed text prefixes so ingestion can read generated artifacts.

## Monitoring

- Dashboard: `StudyBot-W7-Operations`.
- API alarm: API Gateway 5XX sum >= 1 in 5 minutes.
- Lambda alarms: error count >= 1 in 5 minutes for upload, ingestion, Q&A, summary, quiz, planner, and history/dashboard.
- Duration alarms: Q&A p95 > 45 seconds, ingestion p95 > 4 minutes.
- Ingestion failure signal: CloudWatch Logs metric filter `StudyBot/W7/IngestionFailures` on the ProcessPdf Lambda log group.
- Useful logs: `/aws/lambda/<Login|Sessions|Upload|Documents|ProcessPdf|Qa|Summary|Quiz|Planner|History>`.
- Thresholds are intentionally sensitive for W7 demonstration; production thresholds should be tuned to expected traffic.

## Cost

- 48-hour estimate for demo traffic: approximately low single-digit USD, excluding unusual Bedrock/Textract usage.
- Monthly estimate at light classroom/demo usage: CloudFront/S3/DynamoDB/Lambda/API Gateway remain low; Bedrock model calls, Knowledge Base retrieval, Textract fallback, and S3 Vectors dominate variable cost.
- Controls: on-demand DynamoDB, no NAT gateways, small Lambda memory sizes, CloudWatch alarms, limited quiz counts, frontend static hosting, and teardown checklist.
- Budget: if AWS Budgets permissions are available, create a manual monthly budget alarm for this account. If CDK budget deployment is blocked by account permissions, document the manual budget screenshot in this evidence pack.
- Teardown: see [teardown_confirmation.md](teardown_confirmation.md).

## Customization

- Quiz: `/quiz` generates 5-10 document-grounded questions and stores quiz history.
- Flashcards: `/quiz` with `feature=flashcards` returns card-style question/answer items.
- Exam planner: `/planner/clarify` asks for missing required date/hours; `/planner` creates dated study tasks using selected docs, weak topics, and recent quiz topics.
- Weekly topic dashboard: `/dashboard` aggregates activity-derived topics from summaries, quizzes, flashcards, Q&A, and planner history for a rolling 7-day default window.

## Test Evidence

Local verification commands:

```powershell
python -m py_compile BE/src/history/history_lambda.py BE/src/core.py BE/src/planner/planner_lambda.py
python -m unittest BE.tests.test_dashboard
cd FE; npm run build
cd ../infra; cdk synth
```

Live verification:

- Use [smoke_test.md](smoke_test.md) against `https://api.nguyenductien.cloud`.
- Dashboard endpoint: `GET /dashboard?user_id=demo&session_id=all&days=7`.
- Smoke completed on May 28, 2026:
  - Login returned `Login success`.
  - Docs list returned ready document `doc_7e3998e2e2`.
  - Planner clarification returned `ready:false` with missing `exam_date` and `study_hours`.
  - Summary returned 5 `testable_concepts`.
  - Quiz returned 5 questions.
  - Planner create returned `plan_b67815968a` with 48 tasks.
  - Dashboard returned 38 topics after study activity.
  - Q&A endpoint returned 200 but no citations for the selected demo document, with a fallback "not enough grounded context" answer. This is a live data/ingestion quality gap to capture separately from endpoint health.
