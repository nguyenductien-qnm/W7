from aws_cdk import CfnCondition, CfnParameter, Fn, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from constructs import Construct

from .resource_types import KnowledgeBaseResources, LambdaResources, StorageResources


def apply_lambda_permissions(
    scope: Construct,
    *,
    storage: StorageResources,
    kb: KnowledgeBaseResources,
    lambdas: LambdaResources,
    generation_model_arn: str,
    generation_profile_arn: str,
    agentcore_memory_id: CfnParameter,
    has_agentcore_memory_id: CfnCondition,
) -> None:
    stack = Stack.of(scope)
    table_arn = storage.documents_table.table_arn

    def add_ddb_policy(target_lambda: lambda_.Function, actions: list[str]) -> None:
        target_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=actions,
                resources=[table_arn],
            )
        )

    add_ddb_policy(lambdas.login_lambda, ["dynamodb:GetItem", "dynamodb:Scan"])
    add_ddb_policy(
        lambdas.sessions_lambda,
        ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:BatchWriteItem"],
    )
    add_ddb_policy(lambdas.upload_lambda, ["dynamodb:GetItem", "dynamodb:PutItem"])
    add_ddb_policy(lambdas.documents_lambda, ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"])
    add_ddb_policy(lambdas.qa_lambda, ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"])
    add_ddb_policy(lambdas.summary_lambda, ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"])
    add_ddb_policy(lambdas.quiz_lambda, ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"])
    add_ddb_policy(
        lambdas.planner_lambda,
        ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:BatchWriteItem"],
    )
    add_ddb_policy(lambdas.history_lambda, ["dynamodb:Query"])
    add_ddb_policy(lambdas.process_pdf_lambda, ["dynamodb:GetItem", "dynamodb:PutItem"])

    lambdas.upload_lambda.add_to_role_policy(
        iam.PolicyStatement(
            actions=["s3:PutObject"],
            resources=[f"{storage.uploads_bucket.bucket_arn}/raw/*"],
        )
    )
    lambdas.summary_lambda.add_to_role_policy(
        iam.PolicyStatement(
            actions=["s3:GetObject"],
            resources=[f"{storage.uploads_bucket.bucket_arn}/processed/*"],
        )
    )
    lambdas.qa_lambda.add_to_role_policy(
        iam.PolicyStatement(
            actions=["s3:GetObject"],
            resources=[f"{storage.uploads_bucket.bucket_arn}/processed/*"],
        )
    )
    lambdas.process_pdf_lambda.add_to_role_policy(
        iam.PolicyStatement(
            actions=["s3:GetObject"],
            resources=[f"{storage.uploads_bucket.bucket_arn}/raw/*"],
        )
    )
    lambdas.process_pdf_lambda.add_to_role_policy(
        iam.PolicyStatement(
            actions=["s3:PutObject", "s3:DeleteObject"],
            resources=[f"{storage.uploads_bucket.bucket_arn}/processed/*"],
        )
    )
    lambdas.process_pdf_lambda.add_to_role_policy(
        iam.PolicyStatement(
            actions=["s3:ListBucket"],
            resources=[storage.uploads_bucket.bucket_arn],
        )
    )

    lambdas.documents_lambda.add_to_role_policy(
        iam.PolicyStatement(
            actions=["bedrock:GetIngestionJob"],
            resources=[kb.kb_arn, kb.data_source_arn],
        )
    )
    for ai_lambda in [lambdas.qa_lambda, lambdas.summary_lambda, lambdas.quiz_lambda, lambdas.planner_lambda]:
        ai_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:Retrieve"],
                resources=[kb.kb_arn],
            )
        )
        ai_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[generation_model_arn, generation_profile_arn],
            )
        )

    for memory_lambda in [lambdas.qa_lambda, lambdas.planner_lambda]:
        memory_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:CreateEvent",
                    "bedrock-agentcore:RetrieveMemoryRecords",
                ],
                resources=[
                    Fn.condition_if(
                        has_agentcore_memory_id.logical_id,
                        (
                            f"arn:{stack.partition}:bedrock-agentcore:{stack.region}:{stack.account}:"
                            f"memory/{agentcore_memory_id.value_as_string}"
                        ),
                        (
                            f"arn:{stack.partition}:bedrock-agentcore:{stack.region}:{stack.account}:"
                            "memory/DisabledMemory-0000000000"
                        ),
                    ).to_string()
                ],
            )
        )

    lambdas.process_pdf_lambda.add_to_role_policy(
        iam.PolicyStatement(
            actions=[
                "bedrock:StartIngestionJob",
                "bedrock:GetIngestionJob",
                "bedrock:ListIngestionJobs",
            ],
            resources=[kb.kb_arn, kb.data_source_arn],
        )
    )
    lambdas.process_pdf_lambda.add_to_role_policy(
        iam.PolicyStatement(
            actions=["textract:StartDocumentTextDetection", "textract:GetDocumentTextDetection"],
            resources=["*"],
        )
    )

    for suffix in [".pdf", ".docx", ".md", ".markdown", ".txt", ".pptx", ".vtt"]:
        storage.uploads_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(lambdas.process_pdf_lambda),
            s3.NotificationKeyFilter(prefix="raw/", suffix=suffix),
        )
