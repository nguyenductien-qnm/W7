# StudyBot Architecture

This diagram is the version to use in the W7 report/demo. It separates the public edge, API layer, private Lambda layer, storage/data layer, Bedrock retrieval layer, and monitoring layer. It also shows that `ProcessPdfLambda` is not called by API Gateway; it is triggered asynchronously by S3 object-created events.

## Mermaid Diagram

```mermaid
flowchart LR
  user["User Browser"]

  subgraph public_edge["Public Edge / Frontend Hosting"]
    route53["Amazon Route 53<br/>nguyenductien.cloud"]
    cloudfront["Amazon CloudFront<br/>Frontend distribution"]
    frontend_bucket["Amazon S3 Frontend Bucket<br/>private bucket, CloudFront access only"]
  end

  subgraph api_edge["Public API Layer"]
    api_domain["Custom API Domain<br/>api.nguyenductien.cloud"]
    api_gateway["Amazon API Gateway HTTP API<br/>API id: 3sgavxe4c0"]
  end

  subgraph vpc["Amazon Virtual Private Cloud<br/>vpc-06d2de3b6e14576ca"]
    subgraph private_subnets["Private Isolated Subnets"]
      core_api_lambdas["AWS Lambda group<br/>Core API functions<br/>Login, Sessions, Documents"]
      upload_api_lambda["AWS Lambda group<br/>Upload API function<br/>Presign, direct upload, completion"]
      ai_study_lambdas["AWS Lambda group<br/>AI Study functions<br/>Question Answering, Summary, Quiz, Flashcards"]
      planning_activity_lambdas["AWS Lambda group<br/>Planning and Activity functions<br/>Exam Planner, History, Dashboard"]
      ingestion_worker_lambda["AWS Lambda<br/>Document Ingestion worker<br/>ProcessPdfLambda<br/>not API Gateway invoked"]
    end

    subgraph vpc_endpoints["VPC Endpoints"]
      s3_endpoint["Amazon S3 Gateway Endpoint"]
      dynamodb_endpoint["Amazon DynamoDB Gateway Endpoint"]
      bedrock_runtime_endpoint["Amazon Bedrock Runtime Interface Endpoint"]
      bedrock_agent_endpoint["Amazon Bedrock Agent Interface Endpoint"]
      bedrock_agent_runtime_endpoint["Amazon Bedrock Agent Runtime Interface Endpoint"]
      textract_endpoint["Amazon Textract Interface Endpoint"]
    end
  end

  subgraph storage_data["Storage and Application Data"]
    documents_table["Amazon DynamoDB<br/>StudyBotDocuments table<br/>users, sessions, documents, history, plans, dashboard activity"]
    uploads_bucket["Amazon S3 Upload Bucket<br/>raw documents and processed text"]
  end

  subgraph bedrock_layer["AI and Retrieval Layer"]
    textract["Amazon Textract<br/>text extraction fallback"]
    knowledge_base["Amazon Bedrock Knowledge Base<br/>AXVC1I6AQN"]
    vector_index["Amazon S3 Vectors<br/>studybot-kb-index-v2"]
    bedrock_model["Amazon Bedrock Model<br/>answer, summary, quiz, planner generation"]
    agentcore["Amazon Bedrock AgentCore Gateway / Memory<br/>studybot-tools-jvjik80lgi"]
  end

  subgraph observability["Monitoring and Operations"]
    cloudwatch["Amazon CloudWatch<br/>logs, dashboard, metrics, alarms"]
  end

  user -->|"loads app"| route53
  route53 --> cloudfront
  cloudfront --> frontend_bucket

  user -->|"HTTPS API calls"| api_domain
  api_domain --> api_gateway

  api_gateway -->|"login, session, document list routes"| core_api_lambdas
  api_gateway -->|"upload routes"| upload_api_lambda
  api_gateway -->|"question answering, summary, quiz routes"| ai_study_lambdas
  api_gateway -->|"planner, history, dashboard routes"| planning_activity_lambdas

  core_api_lambdas -->|"read/write user, session, document metadata"| documents_table
  upload_api_lambda -->|"write upload metadata"| documents_table
  ai_study_lambdas -->|"save questions, summaries, quizzes, flashcards"| documents_table
  planning_activity_lambdas -->|"read activity and save plans/dashboard data"| documents_table
  ingestion_worker_lambda -->|"update ingestion status"| documents_table

  upload_api_lambda -->|"presigned upload / direct upload"| uploads_bucket
  uploads_bucket -->|"Amazon S3 object-created event"| ingestion_worker_lambda
  ingestion_worker_lambda -->|"writes processed text"| uploads_bucket
  ingestion_worker_lambda -->|"optional extraction fallback"| textract
  ingestion_worker_lambda -->|"starts ingestion job"| knowledge_base
  knowledge_base --> vector_index

  ai_study_lambdas -->|"retrieve document context"| knowledge_base
  planning_activity_lambdas -->|"retrieve context for plans"| knowledge_base

  ai_study_lambdas -->|"invoke model for answers, summaries, quizzes"| bedrock_model
  planning_activity_lambdas -->|"invoke model for planning"| bedrock_model

  ai_study_lambdas -->|"conversation memory"| agentcore
  planning_activity_lambdas -->|"study planning and tool history context"| agentcore

  s3_endpoint -.-> uploads_bucket
  dynamodb_endpoint -.-> documents_table
  bedrock_runtime_endpoint -.-> bedrock_model
  bedrock_agent_endpoint -.-> knowledge_base
  bedrock_agent_runtime_endpoint -.-> agentcore
  textract_endpoint -.-> textract

  api_gateway --> cloudwatch
  core_api_lambdas --> cloudwatch
  upload_api_lambda --> cloudwatch
  ai_study_lambdas --> cloudwatch
  planning_activity_lambdas --> cloudwatch
  ingestion_worker_lambda --> cloudwatch

  classDef public fill:#e0f2fe,stroke:#0284c7,color:#0f172a;
  classDef api fill:#ede9fe,stroke:#7c3aed,color:#0f172a;
  classDef lambda fill:#ffedd5,stroke:#f97316,color:#111827;
  classDef data fill:#dcfce7,stroke:#16a34a,color:#111827;
  classDef ai fill:#ccfbf1,stroke:#0f766e,color:#111827;
  classDef monitor fill:#fee2e2,stroke:#dc2626,color:#111827;
  classDef endpoint fill:#f5f3ff,stroke:#8b5cf6,color:#111827;

  class route53,cloudfront,frontend_bucket public;
  class api_domain,api_gateway api;
  class core_api_lambdas,upload_api_lambda,ai_study_lambdas,planning_activity_lambdas,ingestion_worker_lambda lambda;
  class documents_table,uploads_bucket data;
  class textract,knowledge_base,vector_index,bedrock_model,agentcore ai;
  class cloudwatch monitor;
  class s3_endpoint,dynamodb_endpoint,bedrock_runtime_endpoint,bedrock_agent_endpoint,bedrock_agent_runtime_endpoint,textract_endpoint endpoint;
```

## How To Read It

- The browser loads the React frontend through Route 53, CloudFront, and a private Amazon S3 frontend bucket.
- The browser calls `https://api.nguyenductien.cloud`, which routes through Amazon API Gateway HTTP API.
- API Gateway invokes the user-facing AWS Lambda functions: login, sessions, upload, documents, question answering, summary, quiz and flashcards, planner, and history/dashboard.
- `ProcessPdfLambda` is different: it is triggered by Amazon S3 object-created events after a document upload.
- The Lambda functions correlate through shared services, mainly Amazon DynamoDB, Amazon S3, Amazon Bedrock Knowledge Base, Amazon S3 Vectors, and Amazon Bedrock AgentCore.
- The private Lambda layer uses VPC endpoints to reach AWS services without needing a public NAT gateway.
- Amazon CloudWatch collects API metrics, Lambda logs, dashboard metrics, and alarms.

## Main Flows

### Frontend Load

```text
User Browser
  -> Amazon Route 53
  -> Amazon CloudFront
  -> Amazon S3 frontend bucket
  -> React StudyBot app
```

### API Request

```text
React StudyBot app
  -> api.nguyenductien.cloud
  -> Amazon API Gateway HTTP API
  -> Feature-specific AWS Lambda
  -> Amazon DynamoDB / Amazon Bedrock / Amazon S3
  -> Response to browser
```

### Document Ingestion

```text
Upload Lambda
  -> Amazon S3 upload bucket
  -> S3 object-created event
  -> ProcessPdfLambda
  -> processed text in Amazon S3
  -> Amazon Bedrock Knowledge Base ingestion
  -> Amazon S3 Vectors index
```

### Dashboard

```text
React StudyBot app
  -> GET /dashboard
  -> History and Dashboard Lambda
  -> Amazon DynamoDB recent activity
  -> topics studied this week
```

## Current Live Resource Names

- Stack: `StudyBotInfraStack`
- Status checked: `UPDATE_COMPLETE`
- Frontend: `https://nguyenductien.cloud`
- API: `https://api.nguyenductien.cloud`
- API Gateway id: `3sgavxe4c0`
- VPC: `vpc-06d2de3b6e14576ca`
- DynamoDB table: `StudyBotInfraStack-StudyBotDocuments5485FA25-OOQB8FWTKUX8`
- Upload bucket: `studybotinfrastack-studybotuploadsa01cf717-yffnnbch9sde`
- Frontend bucket: `studybotinfrastack-studybotfrontendbucket0d64d827-ve7senepf9rg`
- CloudFront domain: `d202pyjoa7b4uh.cloudfront.net`
- Bedrock Knowledge Base: `AXVC1I6AQN`
- Bedrock data source: `FHGHEZJFOY`
- S3 Vectors index: `studybot-kb-index-v2`
- AgentCore Gateway: `studybot-tools-jvjik80lgi`
- CloudWatch dashboard: `StudyBot-W7-Operations`
