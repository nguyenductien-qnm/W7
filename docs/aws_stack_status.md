# Current AWS Stack Status

Checked on May 29, 2026 with:

```powershell
aws cloudformation describe-stacks --stack-name StudyBotInfraStack --region ap-southeast-1
cd infra; cdk diff StudyBotInfraStack
```

## CloudFormation

- Stack: `StudyBotInfraStack`
- Status: `UPDATE_COMPLETE`
- Last updated: `2026-05-28T18:51:13Z`
- Region: `ap-southeast-1`
- API custom domain: `api.nguyenductien.cloud`
- Frontend domain: `nguyenductien.cloud`
- HTTP API URL: `https://3sgavxe4c0.execute-api.ap-southeast-1.amazonaws.com`
- VPC: `vpc-06d2de3b6e14576ca`
- DynamoDB table: `StudyBotInfraStack-StudyBotDocuments5485FA25-OOQB8FWTKUX8`
- Upload bucket: `studybotinfrastack-studybotuploadsa01cf717-yffnnbch9sde`
- Frontend bucket: `studybotinfrastack-studybotfrontendbucket0d64d827-ve7senepf9rg`
- CloudFront distribution domain: `d202pyjoa7b4uh.cloudfront.net`
- Bedrock Knowledge Base: `AXVC1I6AQN`
- Bedrock data source: `FHGHEZJFOY`
- Bedrock data source name: `studybot-kb-ds-v2`
- Bedrock fixed chunking: `300` max tokens, `15` percent overlap
- Vector index ARN: `arn:aws:s3vectors:ap-southeast-1:589077667575:bucket/studybotinfrastack-studybotknowledgebasevectorbuck-t9bgmpd2yqk1/index/studybot-kb-index-v2`
- AgentCore Gateway: `studybot-tools-jvjik80lgi`
- CloudWatch dashboard: `StudyBot-W7-Operations`

## CDK Diff Finding

After the May 29 deploy, `cdk deploy StudyBotInfraStack --require-approval never --outputs-file outputs.json` completed successfully.

Confirmed live checks:

- Resource Groups Tagging API returns 49 resources with `Project=W7Capstone` and `Team=G11`.
- Bedrock data source `FHGHEZJFOY` reports fixed chunking at `300` tokens with `15` percent overlap.
- Frontend returns HTTP 200 at `https://nguyenductien.cloud`.

No live table, upload bucket, Bedrock Knowledge Base, data source, or vector index repointing was shown in the latest diff.
