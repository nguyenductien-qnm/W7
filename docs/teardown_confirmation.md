# W7 Teardown Confirmation

Use this after grading is complete. Teardown is not executed before the
demo because the live URL and API must remain available for assessment.

## Prepared Before Grading

- [x] Teardown commands documented below.
- [x] Current resource identifiers recorded in `infra/outputs.json`.
- [x] Graded evidence explains that final deletion proof is captured only after grading.
- [x] Stack tags are deployed for resource discovery:
  `Project=W7Capstone`, `Team=G11`, `Owner=DinhDanhNam`, `Environment=hackathon`.
- [x] AWS Budgets safety net exists: `StudyBot-W7-weekly-safety-net`.
- [x] Cost Anomaly Detection exists: `Default-Services-Monitor` with confirmed email subscription.

## Final Proof To Capture After Teardown

- [ ] CloudFormation stack deletion status or CLI output.
- [ ] Resource Groups Tagging API check for remaining `Project=W7Capstone` resources.
- [ ] Final Cost Explorer screenshot or CLI export after billing data updates.

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
- [ ] Bedrock data source `FHGHEZJFOY` (`studybot-kb-ds-v2`).
- [ ] S3 Vectors index `studybot-kb-index-v2`.
- [ ] S3 Vectors bucket `studybotinfrastack-studybotknowledgebasevectorbuck-t9bgmpd2yqk1`.

## Evidence

- [ ] Save final CloudFormation deletion screenshot or CLI output.
- [ ] Save final billing/cost explorer screenshot after resources are removed.
