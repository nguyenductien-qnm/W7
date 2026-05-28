# StudyBot W7 Architecture

```mermaid
flowchart LR
  Browser[Browser / EduBot UI] --> CF[CloudFront distribution]
  CF --> S3FE[S3 private frontend bucket]
  Browser --> APIDomain[api.nguyenductien.cloud]
  APIDomain --> HttpApi[API Gateway HTTP API]

  HttpApi --> Login[Login Lambda]
  HttpApi --> Sessions[Sessions Lambda]
  HttpApi --> Upload[Upload Lambda]
  HttpApi --> Docs[Documents Lambda]
  HttpApi --> QA[Q&A Lambda]
  HttpApi --> Summary[Summary Lambda]
  HttpApi --> Quiz[Quiz / Flashcards Lambda]
  HttpApi --> Planner[Exam Planner Lambda]
  HttpApi --> History[History / Dashboard Lambda]

  Upload --> RawS3[S3 raw uploads]
  RawS3 --> Ingestion[ProcessPdf Lambda]
  Ingestion --> ProcessedS3[S3 processed text]
  Ingestion --> BedrockKB[Bedrock Knowledge Base]
  QA --> BedrockKB
  Summary --> BedrockKB
  Quiz --> BedrockKB
  Planner --> BedrockKB
  QA --> AgentCore[Bedrock AgentCore Memory]
  Planner --> AgentCore

  Login --> DDB[DynamoDB StudyBotDocuments]
  Sessions --> DDB
  Upload --> DDB
  Docs --> DDB
  QA --> DDB
  Summary --> DDB
  Quiz --> DDB
  Planner --> DDB
  History --> DDB

  BedrockKB --> S3Vectors[S3 Vectors index]
  Ingestion --> Textract[Textract fallback]
  Ingestion --> CloudWatch[CloudWatch logs / metrics]
  HttpApi --> CloudWatch
  QA --> CloudWatch
```

## Notes

- Frontend: Vite React app in `FE`, deployed to S3 behind CloudFront for `https://nguyenductien.cloud`.
- API: API Gateway HTTP API with custom domain `https://api.nguyenductien.cloud`.
- Compute: Python 3.12 Lambda functions packaged from `BE/src`.
- Data: DynamoDB single-table design keyed by `PK=USER#{user_id}` and `SK`.
- RAG: Bedrock Knowledge Base `LI32IWLOB5` with S3 Vectors index `studybot-kb-index`.
- Network: Lambdas run in private isolated subnets with VPC endpoints for S3, DynamoDB, Bedrock, Bedrock Agent Runtime, and Textract.
- Observability: CloudWatch dashboard `StudyBot-W7-Operations`, API 5XX alarm, Lambda error alarms, Q&A/ingestion duration alarms, and ingestion failure log metric.
