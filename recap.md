# AgentCore Tooling and Exam Planner Recap

## Objective

Refactor the StudyBot chatbot architecture so backend capabilities can run as server-side tools while keeping the React frontend on the existing HTTP API boundary. Add Exam Planner v1, backed by DynamoDB history and optional AgentCore Memory.

## Backend Changes

- Added a shared tool contract layer in `BE/src/tool_contract.py`.
  - Supports a common request envelope with `user_id`, `session_id`, `selected_doc_ids`, `input`, and `metadata`.
  - Supports a common response envelope with `tool_name`, `status`, `data`, `citations`, and `errors`.
  - Lets handlers accept both normal API Gateway HTTP events and AgentCore-style tool invocation events.

- Added best-effort AgentCore Memory utilities in `BE/src/memory_utils.py`.
  - Uses `AGENTCORE_MEMORY_ID` and optional `AGENTCORE_MEMORY_STRATEGY_ID`.
  - Writes conversational events with `actorId = user_id` and `sessionId = session_id`.
  - Retrieves relevant memory records when configured.
  - Fails closed to no-op behavior when memory is not configured or unavailable, preserving local/mock flows.

- Updated existing Lambda handlers for tool compatibility.
  - `BE/src/qa_lambda.py` now exposes `ask_documents`.
  - `BE/src/summary_lambda.py` now exposes `summarize_documents`.
  - `BE/src/quiz_lambda.py` now exposes `generate_quiz` and `generate_flashcards`.
  - `BE/src/history_lambda.py` now exposes `get_history`.
  - `BE/src/app.py` now supports `list_documents` tool invocation.

- Added Exam Planner v1 in `BE/src/planner_lambda.py`.
  - Exposes `create_exam_plan`.
  - Requires `exam_date`, study availability, and selected documents.
  - Supports daily or weekly study hours.
  - Supports optional target grade, weak topics, excluded days, and preferred session length.
  - Produces dated tasks ending on or before the exam date.
  - Stores both latest/history-style planner records in DynamoDB under the active session.
  - Uses selected document concepts, recent quiz topics, weak topics, and optional AgentCore Memory.

- Updated history rendering in `BE/src/history_lambda.py`.
  - Planner records are returned as chat history messages.
  - Planner output includes a `plan` payload for frontend rendering.

- Updated backend dependency packaging in `BE/src/requirements.txt`.
  - Changed `boto3` to `boto3>=1.43.14` so Lambda packages can include AgentCore data-plane clients.

## Frontend Changes

- Enabled the existing Exam Planner menu item in `FE/src/App.jsx`.
  - Removed the placeholder toast that said planning was not wired.
  - Added `planning` to `FEATURES`.
  - Planner prompts are sent to `/planner`.

- Added simple planner prompt parsing in `FE/src/App.jsx`.
  - Extracts exam date from `YYYY-MM-DD`.
  - Extracts daily or weekly study hours from text such as `2 hours daily` or `10 hours weekly`.
  - Extracts optional weak topics, excluded days, target grade, and preferred session length when present.

- Added planner result rendering.
  - Shows a concise text summary in the chat bubble.
  - Renders dated task rows with date, topic, duration, activity, and reason.

- Added planner styles in `FE/src/App.css`.
  - Responsive planner task layout for desktop and mobile.

## Infrastructure Changes

- Updated `BE/template.yaml`.
  - Added `/planner` route and `PlannerFunction`.
  - Added memory env vars to QA and planner functions.
  - Added AgentCore Memory IAM actions for QA and planner.
  - Removed reserved `AWS_REGION` Lambda environment variables so SAM lint passes.
  - Added `X-Session-Id` and `DELETE` to CORS configuration.

- Updated `infra/studybot_infra/studybot_stack.py`.
  - Added `StudyBotPlannerLambda`.
  - Added `/planner` HTTP route.
  - Added optional `AgentCoreMemoryId` and `AgentCoreMemoryStrategyId` CDK parameters.
  - Added AgentCore Memory permissions for QA and planner.
  - Added AgentCore Gateway role.
  - Added CloudFormation-level `AWS::BedrockAgentCore::Gateway`.
  - Added `AWS::BedrockAgentCore::GatewayTarget` Lambda targets for:
    - `list_documents`
    - `ask_documents`
    - `summarize_documents`
    - `generate_quiz`
    - `generate_flashcards`
    - `create_exam_plan`
    - `get_history`

## Verification Completed

- Backend compile passed:

```powershell
Get-ChildItem BE\src -Filter *.py | ForEach-Object { python -m py_compile $_.FullName }
```

- Frontend production build passed:

```powershell
cd FE
npm run build
```

- Planner handler checks passed:
  - Missing `exam_date` rejects with HTTP 400.
  - Tool invocation envelope returns `status: error` for missing required inputs.
  - Stubbed successful planner generation returns dated tasks.
  - Generated tasks end before or on the exam date.
  - Planner stores two DynamoDB records in the success path.
  - Tool invocation envelope returns `status: success` for valid planner input.

- SAM validation passed:

```powershell
cd BE
sam validate --lint
```

## Deployment Caveat

- `cdk synth` was attempted but could not complete because Docker Desktop was not running or unavailable.
  - Failure was from the CDK Lambda bundling Docker step.
  - Error indicated the `dockerDesktopLinuxEngine` pipe was missing.
  - This was an environment/tooling issue, not a Python/React compile failure.

## Existing Worktree Notes

- The repo already had modified `FE/src/App.jsx` and `FE/src/App.css` before this implementation.
- There were also untracked `BE/scripts/src/` and `frontend/` directories before this implementation.
- Those pre-existing changes were left in place and not reverted.

## Current Behavior

- The frontend still calls backend HTTP endpoints.
- AgentCore Gateway is configured as a server-side tool layer in infrastructure.
- Existing HTTP features continue to use `/ask`, `/summary`, `/quiz`, and `/history`.
- Exam Planner now uses `/planner`.
- Tool-compatible Lambdas can be invoked by AgentCore Gateway without exposing Gateway directly to the browser.
- AgentCore Memory is optional and only active when memory environment variables are configured.
