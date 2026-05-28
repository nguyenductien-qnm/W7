from pathlib import Path

from aws_cdk import Duration
from aws_cdk import CfnParameter
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

from .bundling import ReuseBackendBundle
from .resource_types import KnowledgeBaseResources, LambdaResources, NetworkResources, StorageResources


def create_lambda_resources(
    scope: Construct,
    *,
    network: NetworkResources,
    storage: StorageResources,
    kb: KnowledgeBaseResources,
    generation_model_id: str,
    agentcore_memory_id: CfnParameter,
    agentcore_memory_strategy_id: CfnParameter,
) -> LambdaResources:
    backend_src_path = str(Path(__file__).resolve().parents[2] / "BE" / "src")
    backend_lambda_code = lambda_.Code.from_asset(
        backend_src_path,
        exclude=[
            ".env",
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".pytest_cache",
        ],
        bundling={
            "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
            "local": ReuseBackendBundle(backend_src_path),
            "command": [
                "bash",
                "-c",
                (
                    "python -m pip install -r /asset-input/requirements.txt -t /asset-output "
                    "&& cp -r /asset-input/. /asset-output "
                    "&& find /asset-output -type d -name __pycache__ -prune -exec rm -rf {} + "
                    "&& rm -f /asset-output/.env"
                ),
            ],
        },
    )

    shared_environment = {
        "DOCUMENTS_TABLE": storage.documents_table.table_name,
        "INGESTION_MODE": "bedrock",
        "UPLOADS_BUCKET_NAME": storage.uploads_bucket.bucket_name,
        "BEDROCK_KNOWLEDGE_BASE_ID": kb.knowledge_base_id,
        "BEDROCK_DATA_SOURCE_ID": kb.data_source_id,
        "BEDROCK_GENERATION_MODEL_ID": generation_model_id,
        "VECTOR_INDEX_ARN": kb.vector_index_arn,
    }

    login_lambda = lambda_.Function(
        scope,
        "StudyBotLoginLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="auth.login_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.seconds(30),
        memory_size=512,
        **network.lambda_network_config,
        environment=shared_environment,
    )
    sessions_lambda = lambda_.Function(
        scope,
        "StudyBotSessionsLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="session.sessions_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.seconds(30),
        memory_size=512,
        **network.lambda_network_config,
        environment=shared_environment,
    )
    upload_lambda = lambda_.Function(
        scope,
        "StudyBotUploadLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="upload.upload_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.seconds(30),
        memory_size=512,
        **network.lambda_network_config,
        environment=shared_environment,
    )
    documents_lambda = lambda_.Function(
        scope,
        "StudyBotDocumentsLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="documents.documents_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.seconds(30),
        memory_size=512,
        **network.lambda_network_config,
        environment=shared_environment,
    )

    ai_lambda_environment = {
        **shared_environment,
        "AGENTCORE_MEMORY_ID": agentcore_memory_id.value_as_string,
        "AGENTCORE_MEMORY_STRATEGY_ID": agentcore_memory_strategy_id.value_as_string,
    }
    qa_lambda = lambda_.Function(
        scope,
        "StudyBotQaLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="qa.qa_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.seconds(60),
        memory_size=512,
        **network.lambda_network_config,
        environment=ai_lambda_environment,
    )
    summary_lambda = lambda_.Function(
        scope,
        "StudyBotSummaryLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="summary.summary_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.seconds(60),
        memory_size=512,
        **network.lambda_network_config,
        environment=ai_lambda_environment,
    )
    quiz_lambda = lambda_.Function(
        scope,
        "StudyBotQuizLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="quiz.quiz_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.seconds(60),
        memory_size=512,
        **network.lambda_network_config,
        environment=ai_lambda_environment,
    )
    planner_lambda = lambda_.Function(
        scope,
        "StudyBotPlannerLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="planner.planner_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.seconds(60),
        memory_size=512,
        **network.lambda_network_config,
        environment=ai_lambda_environment,
    )
    history_lambda = lambda_.Function(
        scope,
        "StudyBotHistoryLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="history.history_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.seconds(30),
        memory_size=512,
        **network.lambda_network_config,
        environment=ai_lambda_environment,
    )
    process_pdf_lambda = lambda_.Function(
        scope,
        "ProcessPdfLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="ingestion.process_pdf_lambda.lambda_handler",
        code=backend_lambda_code,
        timeout=Duration.minutes(5),
        memory_size=1024,
        **network.lambda_network_config,
        environment={
            "DOCUMENTS_TABLE": storage.documents_table.table_name,
            "UPLOADS_BUCKET_NAME": storage.uploads_bucket.bucket_name,
            "BEDROCK_KNOWLEDGE_BASE_ID": kb.knowledge_base_id,
            "BEDROCK_DATA_SOURCE_ID": kb.data_source_id,
            "KB_PROCESSED_PREFIX": "processed",
            "USE_TEXTRACT_FALLBACK": "true",
        },
    )

    return LambdaResources(
        login_lambda=login_lambda,
        sessions_lambda=sessions_lambda,
        upload_lambda=upload_lambda,
        documents_lambda=documents_lambda,
        qa_lambda=qa_lambda,
        summary_lambda=summary_lambda,
        quiz_lambda=quiz_lambda,
        planner_lambda=planner_lambda,
        history_lambda=history_lambda,
        process_pdf_lambda=process_pdf_lambda,
    )
