from aws_cdk import CfnResource, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from .resource_types import AgentCoreResources, LambdaResources


def create_agentcore_resources(
    scope: Construct,
    *,
    lambdas: LambdaResources,
) -> AgentCoreResources:
    stack = Stack.of(scope)

    gateway_role = iam.Role(
        scope,
        "StudyBotAgentCoreGatewayRole",
        assumed_by=iam.ServicePrincipal(
            "bedrock-agentcore.amazonaws.com",
            conditions={
                "StringEquals": {"aws:SourceAccount": stack.account},
                "ArnLike": {
                    "aws:SourceArn": f"arn:{stack.partition}:bedrock-agentcore:{stack.region}:{stack.account}:gateway/*"
                },
            },
        ),
    )
    for target_lambda in [
        lambdas.qa_lambda,
        lambdas.summary_lambda,
        lambdas.quiz_lambda,
        lambdas.planner_lambda,
        lambdas.history_lambda,
    ]:
        target_lambda.grant_invoke(gateway_role)
        target_lambda.add_permission(
            f"AgentCoreInvoke{target_lambda.node.id}",
            principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_account=stack.account,
            source_arn=f"arn:{stack.partition}:bedrock-agentcore:{stack.region}:{stack.account}:gateway/*",
        )

    agentcore_gateway = CfnResource(
        scope,
        "StudyBotAgentCoreGateway",
        type="AWS::BedrockAgentCore::Gateway",
        properties={
            "Name": "studybot-tools",
            "Description": "Server-side StudyBot tools for document study workflows.",
            "AuthorizerType": "AWS_IAM",
            "ProtocolType": "MCP",
            "RoleArn": gateway_role.role_arn,
        },
    )

    def string_schema(description: str) -> dict:
        return {"Type": "string", "Description": description}

    def array_string_schema(description: str) -> dict:
        return {"Type": "array", "Description": description, "Items": {"Type": "string"}}

    tool_input_schema = {
        "Type": "object",
        "Required": ["user_id", "session_id"],
        "Properties": {
            "user_id": string_schema("Application user id."),
            "session_id": string_schema("Active study session id."),
            "selected_doc_ids": array_string_schema("Selected document ids."),
            "plan_id": string_schema("Saved exam plan id."),
            "question": string_schema("User question or prompt."),
            "exam_date": string_schema("Exam date in YYYY-MM-DD format."),
            "daily_study_hours": {"Type": "number", "Description": "Available study hours per day."},
            "weekly_study_hours": {"Type": "number", "Description": "Available study hours per week."},
            "weak_topics": array_string_schema("Known weak topics."),
            "excluded_days": array_string_schema("Dates or weekdays to skip."),
            "preferred_session_length": {"Type": "integer", "Description": "Preferred session length in minutes."},
        },
    }
    tool_output_schema = {
        "Type": "object",
        "Properties": {
            "tool_name": string_schema("Tool name."),
            "status": string_schema("success or error."),
            "data": {"Type": "object", "Description": "Tool result data."},
            "citations": {"Type": "array", "Description": "Grounding citations.", "Items": {"Type": "object"}},
            "errors": {"Type": "array", "Description": "Error messages.", "Items": {"Type": "string"}},
        },
    }

    def add_agentcore_lambda_target(logical_id: str, name: str, description: str, fn, tools: list[tuple[str, str]]) -> CfnResource:
        return CfnResource(
            scope,
            logical_id,
            type="AWS::BedrockAgentCore::GatewayTarget",
            properties={
                "Name": name,
                "Description": description,
                "GatewayIdentifier": agentcore_gateway.ref,
                "CredentialProviderConfigurations": [{"CredentialProviderType": "GATEWAY_IAM_ROLE"}],
                "TargetConfiguration": {
                    "Mcp": {
                        "Lambda": {
                            "LambdaArn": fn.function_arn,
                            "ToolSchema": {
                                "InlinePayload": [
                                    {
                                        "Name": tool_name,
                                        "Description": tool_description,
                                        "InputSchema": tool_input_schema,
                                        "OutputSchema": tool_output_schema,
                                    }
                                    for tool_name, tool_description in tools
                                ]
                            },
                        }
                    }
                },
            },
        )

    add_agentcore_lambda_target(
        "StudyBotQaToolsTarget",
        "studybot-qa-tools",
        "Question answering tools.",
        lambdas.qa_lambda,
        [("ask_documents", "Answer questions from selected documents.")],
    )
    add_agentcore_lambda_target(
        "StudyBotSummaryToolsTarget",
        "studybot-summary-tools",
        "Document summary tools.",
        lambdas.summary_lambda,
        [("summarize_documents", "Summarize selected documents.")],
    )
    add_agentcore_lambda_target(
        "StudyBotQuizToolsTarget",
        "studybot-quiz-tools",
        "Quiz and flashcard generation tools.",
        lambdas.quiz_lambda,
        [
            ("generate_quiz", "Generate quiz questions from selected documents."),
            ("generate_flashcards", "Generate flashcards from selected documents."),
        ],
    )
    add_agentcore_lambda_target(
        "StudyBotPlannerToolsTarget",
        "studybot-planner-tools",
        "Exam planning tools.",
        lambdas.planner_lambda,
        [
            ("create_exam_plan", "Create a dated study plan before an exam."),
            ("recommend_exam_plan_documents", "Recommend ready session documents relevant to a saved exam plan."),
        ],
    )
    add_agentcore_lambda_target(
        "StudyBotHistoryToolsTarget",
        "studybot-history-tools",
        "Session history tools.",
        lambdas.history_lambda,
        [("get_history", "Get UI history for the active study session.")],
    )

    return AgentCoreResources(gateway=agentcore_gateway)
