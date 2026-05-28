from aws_cdk import CfnOutput
from constructs import Construct

from .resource_types import (
    AgentCoreResources,
    ApiResources,
    FrontendResources,
    KnowledgeBaseResources,
    LambdaResources,
    ObservabilityResources,
    StorageResources,
)


def create_outputs(
    scope: Construct,
    *,
    storage: StorageResources,
    kb: KnowledgeBaseResources,
    api: ApiResources,
    frontend: FrontendResources,
    lambdas: LambdaResources,
    observability: ObservabilityResources,
    agentcore: AgentCoreResources,
    root_domain_name: str,
) -> None:
    CfnOutput(scope, "UploadsBucketName", value=storage.uploads_bucket.bucket_name)
    CfnOutput(scope, "DocumentsTableName", value=storage.documents_table.table_name)
    CfnOutput(scope, "VectorIndexArn", value=kb.vector_index_arn)
    CfnOutput(scope, "KnowledgeBaseId", value=kb.knowledge_base_id)
    CfnOutput(scope, "DataSourceId", value=kb.data_source_id)
    CfnOutput(scope, "HttpApiUrl", value=api.http_api.api_endpoint)
    CfnOutput(scope, "ApiCustomDomain", value=api.api_domain_name)
    CfnOutput(scope, "FrontendBucketName", value=storage.frontend_bucket.bucket_name)
    CfnOutput(scope, "FrontendCloudFrontDomain", value=frontend.distribution.domain_name)
    CfnOutput(scope, "FrontendCustomDomain", value=root_domain_name)
    CfnOutput(scope, "LoginLambdaName", value=lambdas.login_lambda.function_name)
    CfnOutput(scope, "SessionsLambdaName", value=lambdas.sessions_lambda.function_name)
    CfnOutput(scope, "UploadLambdaName", value=lambdas.upload_lambda.function_name)
    CfnOutput(scope, "DocumentsLambdaName", value=lambdas.documents_lambda.function_name)
    CfnOutput(scope, "ProcessPdfLambdaName", value=lambdas.process_pdf_lambda.function_name)
    CfnOutput(scope, "QaLambdaName", value=lambdas.qa_lambda.function_name)
    CfnOutput(scope, "SummaryLambdaName", value=lambdas.summary_lambda.function_name)
    CfnOutput(scope, "QuizLambdaName", value=lambdas.quiz_lambda.function_name)
    CfnOutput(scope, "PlannerLambdaName", value=lambdas.planner_lambda.function_name)
    CfnOutput(scope, "HistoryLambdaName", value=lambdas.history_lambda.function_name)
    CfnOutput(scope, "OperationsDashboardName", value=observability.dashboard.dashboard_name)
    CfnOutput(scope, "IngestionFailureMetricName", value="StudyBot/W7/IngestionFailures")
    CfnOutput(scope, "AgentCoreGatewayId", value=agentcore.gateway.ref)
    CfnOutput(scope, "AgentCoreGatewayUrl", value=agentcore.gateway.get_att("GatewayUrl").to_string())
