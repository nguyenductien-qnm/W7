# W7 Teardown Confirmation

Use this after grading is complete.

## Stack

- [ ] Confirm W7 grading is complete.
- [ ] Run `cd infra; cdk destroy StudyBotInfraStack`.
- [ ] Confirm CloudFormation stack `StudyBotInfraStack` is deleted.

## Resources To Verify

- [ ] CloudFront distribution for `nguyenductien.cloud` removed.
- [ ] Frontend S3 bucket from `FrontendBucketName` output emptied/deleted.
- [ ] API Gateway HTTP API and custom domain `api.nguyenductien.cloud` removed.
- [ ] Route 53 records for root, `www`, and `api` removed if no longer needed.
- [ ] ACM certificates for frontend and API removed if no longer needed.
- [ ] Lambda functions removed: Login, Sessions, Upload, Documents, ProcessPdf, Q&A, Summary, Quiz, Planner, History.
- [ ] CloudWatch dashboard `StudyBot-W7-Operations` and W7 alarms removed.
- [ ] VPC, private subnets, security groups, and VPC endpoints removed.

## Shared / Imported Resources

These are imported by CDK and may be shared. Delete only if the project is fully retired.

- [ ] DynamoDB table `StudyBotDocuments`.
- [ ] Upload bucket `studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk`.
- [ ] Bedrock Knowledge Base `LI32IWLOB5`.
- [ ] Bedrock data source `V0ISBKEMXT`.
- [ ] S3 Vectors index `studybot-kb-index`.
- [ ] Bedrock Knowledge Base role `StudyBotBedrockStack-KnowledgeBaseRoleA2B317B9-UycR9VjqexH0`.

## Evidence

- [ ] Save final CloudFormation deletion screenshot or CLI output.
- [ ] Save final billing/cost explorer screenshot after resources are removed.
