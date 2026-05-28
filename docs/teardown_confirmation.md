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

## Data / AI Resources

- [ ] DynamoDB table `StudyBotInfraStack-StudyBotDocuments5485FA25-OOQB8FWTKUX8`.
- [ ] Upload bucket `studybotinfrastack-studybotuploadsa01cf717-yffnnbch9sde`.
- [ ] Bedrock Knowledge Base `AXVC1I6AQN`.
- [ ] Bedrock data source `2Q8XWMU3ER`.
- [ ] S3 Vectors index `studybot-kb-index-v2`.
- [ ] S3 Vectors bucket `studybotinfrastack-studybotknowledgebasevectorbuck-t9bgmpd2yqk1`.

## Evidence

- [ ] Save final CloudFormation deletion screenshot or CLI output.
- [ ] Save final billing/cost explorer screenshot after resources are removed.
