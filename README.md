# StudyBot W7 Capstone

StudyBot is an AI study buddy for uploaded learning documents. It uses a
React frontend, API Gateway HTTP API, Lambda, DynamoDB, S3, Bedrock
Knowledge Base, S3 Vectors, and CloudWatch.

## Live Demo

- Frontend: <https://nguyenductien.cloud>
- API: <https://api.nguyenductien.cloud>
- Demo email: `demo@studybot.com`
- Demo user/session: `demo` / `default`
- Ready demo document: `w7-demo-photosynthesis`

## Submission Artifacts

- Graded evidence pack: [docs/W7_evidence.md](docs/W7_evidence.md)
- Architecture: [docs/architecture.md](docs/architecture.md)
- Smoke test commands: [docs/smoke_test.md](docs/smoke_test.md)
- Stack status: [docs/aws_stack_status.md](docs/aws_stack_status.md)
- Teardown checklist: [docs/teardown_confirmation.md](docs/teardown_confirmation.md)

## Infrastructure

```powershell
cd infra
cdk synth StudyBotInfraStack
cdk deploy StudyBotInfraStack --require-approval never --outputs-file outputs.json
```

Required stack tags are applied at the CDK stack level:
`Project=W7Capstone`, `Team=G11`, `Owner=DinhDanhNam`, and
`Environment=hackathon`.

The deployed Knowledge Base data source uses fixed chunking at 300
tokens with 15% overlap. The active data source is `FHGHEZJFOY`
(`studybot-kb-ds-v2`).

## Smoke Test

Run the commands in [docs/smoke_test.md](docs/smoke_test.md). The latest
verified live smoke passed login, document list, Q&A, summary, quiz,
planner clarification, planner creation, dashboard, and frontend HTTP
200.

## Cost Controls

The chosen optional capability is Advanced Cost Insights. Evidence uses
AWS Budgets budget `StudyBot-W7-weekly-safety-net`, Cost Anomaly
Detection monitor `Default-Services-Monitor`, and a cost-per-feature
breakdown in [docs/W7_evidence.md](docs/W7_evidence.md).

## Teardown

After grading:

```powershell
cd infra
cdk destroy StudyBotInfraStack
```

Then complete [docs/teardown_confirmation.md](docs/teardown_confirmation.md)
with CloudFormation deletion proof and final Cost Explorer proof.
