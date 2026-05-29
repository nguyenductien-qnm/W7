# W7 Submission Gap Audit

Audit date: May 29, 2026

Sources checked:

- `E:\W7\W7\W7_project_announcement.md`
- `E:\W7\W7\W7_learner_guide.md`
- `E:\W7\W7\W7_hackathon_rules.txt`
- deployed `StudyBotInfraStack` in `ap-southeast-1`
- live URLs `https://nguyenductien.cloud` and `https://api.nguyenductien.cloud`
- current graded evidence pack under `docs/W7_evidence.md`

## Critical / High Risk

### 1. Evidence pack is not in the required path

Requirement: `docs/W7_evidence.md` must be committed before the demo slot.

Current state: resolved. The graded evidence pack is `docs/W7_evidence.md`, and figures are copied to `docs/figures/`.

Fix: copy or move the final evidence pack into `docs/W7_evidence.md` and copy the figure folder or adjust image paths.

### 2. Required project tags are missing from the deployed stack

Requirement: every resource should use `Project=W7Capstone`, `Team=G<N>`, `Owner=<name>`, and `Environment=hackathon`.

Current state: `StudyBotInfraStack` has no CloudFormation stack tags. Resource Group Tagging API returned no resources for `Project=W7Capstone`; deployed resources only have CloudFormation/CDK-generated tags.

Fix: add stack-level CDK tags in `infra/app.py` or `StudyBotInfraStack`, redeploy, then confirm via Resource Groups Tagging API and Cost Explorer tag filtering.

### 3. Demo credentials in evidence are wrong

Requirement: trainer must be able to open the public URL and log in.

Current state: resolved. Live `/login` succeeds for `demo@studybot.com`, mapped to user `demo`, and `docs/list` returns ready document `w7-demo-photosynthesis` in session `default`.

Fix: either seed `demo@studybot.com` properly or update the evidence/demo script to a known working email and session with ready documents.

### 4. Live demo data is not currently ready for the documented happy path

Requirement: AI feature must work end-to-end with result visible in UI.

Current state: `GET /docs/list?user_id=demo&session_id=all` returns no documents. The dashboard for `demo` returns zero topics. DynamoDB has some ready document data under other users/sessions, but the documented demo user does not expose it through the current smoke path.

Fix: run a fresh upload/ingestion flow for the chosen demo user, verify a ready document appears in the UI, then run Q&A, summary, quiz, planner, and dashboard once before demo.

### 5. CloudWatch alarms are currently all `INSUFFICIENT_DATA`

Requirement for optional Full Observability: at least one alarm in `OK` or `ALARM`, not `INSUFFICIENT_DATA`.

Current state: 11 StudyBot CloudWatch alarms exist, but the latest check showed all 11 in `INSUFFICIENT_DATA`.

Fix: exercise the live API and Lambda paths to emit fresh metrics, then verify at least one alarm returns to `OK` or deliberately trigger a safe test alarm state.

## Medium Risk

### 6. Cost evidence screenshots are incomplete

Requirement: three Cost Explorer screenshots: Wednesday EOD, Thursday EOD, and Friday morning pre-demo.

Current state: the evidence pack contains architecture/security/monitoring screenshots, but no clear Cost Explorer screenshots for the three required time points.

Fix: capture and add the three Cost Explorer screenshots, ideally filtered/grouped by service and, after tags are fixed, filtered by `Team=G11`.

### 7. Cost Anomaly Detection exists but is not W7-specific in evidence

Requirement: Cost Anomaly Detection enabled at account level; Advanced Cost Insights expects alert demo evidence.

Current state: account has `Default-Services-Monitor` and a confirmed email subscription, but it appears older/default rather than newly documented for W7. The evidence pack mentions budget alarms but does not include Cost Anomaly Detection evidence.

Fix: add screenshot/evidence of the anomaly monitor and subscription, or create a W7-named monitor/subscription if the team wants the evidence to be clearly project-specific.

### 8. Budget alarm was created after deployment, not pre-flight

Requirement: budget alert at $80/80% before paid infrastructure.

Current state: `StudyBot-W7-weekly-safety-net` now exists with USD 100 limit and 50/80/100 actual plus 100 forecast notifications, but it was created after the stack was already deployed.

Fix: keep the new budget as current evidence, but be honest in Q&A if asked. For the report, phrase it as current spend-control evidence, not as pre-flight evidence.

### 9. Evidence cost estimate includes KMS cost, but stack uses S3-managed encryption

Requirement/security evidence may ask for KMS key ARN if advanced security is claimed.

Current state: S3 upload bucket encryption is `AES256` SSE-S3; DynamoDB SSE description is null/default; the active CDK stack does not define a project KMS CMK. The evidence cost table includes KMS cost, which is not backed by the deployed stack.

Fix: either remove KMS cost/claims from the evidence pack or add a real KMS CMK with rotation and apply it to S3/DynamoDB if choosing Advanced Security.

### 10. Optional capability is unclear

Requirement: pick one optional capability and do it well.

Current state:

- Observability: dashboard, alarms, metric filter, and Logs Insights exist, but no `PutMetricData` custom metric was found and alarms are currently `INSUFFICIENT_DATA`.
- Advanced Cost Insights: selected path. Budget, Cost Anomaly Detection, cost-per-feature analysis, and current Cost Explorer/CLI evidence are documented in `docs/W7_evidence.md`; historical screenshots remain unavailable.
- Advanced Security: IAM/network evidence exists, but no deep KMS/Config/GuardDuty/WAF/etc. implementation is clearly deployed.

Fix: choose one optional path explicitly in the evidence pack and close its exact gaps. The fastest path is likely Observability or Cost Insights.

## Lower Risk / Documentation Gaps

### 11. `docs/teardown_confirmation.md` is only a plan

Requirement: teardown confirmation is due after Sunday June 1 EOD with proof that resources were deleted and Cost Explorer is near zero.

Current state: checklist exists but is unchecked because resources are still deployed.

Fix: after demo, run teardown, check boxes, capture Cost Explorer screenshot on Monday, and commit proof.

### 12. README deliverable is weak/missing at repo root

Requirement: GitHub repo public README should include setup, architecture, and teardown commands.

Current state: no root `README.md` was found in `E:\W7`; there is a `frontend/README.md`, but the main repo landing page may not guide trainers.

Fix: add root `README.md` with live URL, demo credentials, architecture link, deployment commands, smoke test commands, and teardown commands.

### 13. Demo backup video/slides were not found

Requirement guidance strongly recommends a 3-minute demo backup video and slides.

Current state: no `.mp4` or `.pdf` slides were found in the repo root/docs/evidence pack search.

Fix: add `docs/demo.mp4` or an unlisted video link and `docs/slides.pdf` if not already hosted elsewhere.

## Current Strengths

- Public frontend returns HTTP 200 at `https://nguyenductien.cloud`.
- Deployed stack is `UPDATE_COMPLETE`.
- API custom domain exists: `https://api.nguyenductien.cloud`.
- Mandatory architecture layers are present: CloudFront/S3, API Gateway, Lambda, DynamoDB, S3, Bedrock KB/S3 Vectors, VPC endpoints, IAM roles, CloudWatch.
- Root MFA screenshot exists in the evidence pack.
- New W7 budget exists: `StudyBot-W7-weekly-safety-net`, USD 100, May 27 to June 4, 2026, with email notifications.
- Cost Anomaly Detection exists at account level with a confirmed email subscription.
