from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import aws_apigatewayv2 as apigatewayv2
from aws_cdk import aws_apigatewayv2_integrations as apigatewayv2_integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from constructs import Construct
from pathlib import Path


class StudyBotInfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        uploads_bucket_name = "studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk"
        documents_table_name = "StudyBotDocuments"
        vector_index_arn = (
            "arn:aws:s3vectors:ap-southeast-1:589077667575:bucket/"
            "studybot-vectors-589077667575-ap-southeast-1/index/studybot-kb-index"
        )
        knowledge_base_id = "LI32IWLOB5"
        data_source_id = "V0ISBKEMXT"
        generation_model_id = "global.amazon.nova-2-lite-v1:0"
        kb_arn = (
            "arn:aws:bedrock:ap-southeast-1:589077667575:"
            f"knowledge-base/{knowledge_base_id}"
        )
        data_source_arn = (
            "arn:aws:bedrock:ap-southeast-1:589077667575:"
            f"knowledge-base/{knowledge_base_id}/data-source/{data_source_id}"
        )
        generation_profile_arn = (
            "arn:aws:bedrock:*::"
            "foundation-model/amazon.nova-2-lite-v1:0"
        )
        generation_model_arn = (
            "arn:aws:bedrock:ap-southeast-1:589077667575:"
            f"inference-profile/{generation_model_id}"
        )

        uploads_bucket = s3.Bucket.from_bucket_name(
            self,
            "StudyBotUploads",
            bucket_name=uploads_bucket_name,
        )

        documents_table = dynamodb.Table.from_table_name(
            self,
            "StudyBotDocuments",
            table_name=documents_table_name,
        )

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

        api_lambda = lambda_.Function(
            self,
            "StudyBotApiLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="app.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "DOCUMENTS_TABLE": documents_table.table_name,
                "INGESTION_MODE": "bedrock",
                "UPLOADS_BUCKET_NAME": uploads_bucket_name,
                "BEDROCK_KNOWLEDGE_BASE_ID": knowledge_base_id,
                "BEDROCK_DATA_SOURCE_ID": data_source_id,
                "BEDROCK_GENERATION_MODEL_ID": generation_model_id,
                "VECTOR_INDEX_ARN": vector_index_arn,
            },
        )

        ai_lambda_environment = {
            "DOCUMENTS_TABLE": documents_table.table_name,
            "INGESTION_MODE": "bedrock",
            "BEDROCK_KNOWLEDGE_BASE_ID": knowledge_base_id,
            "BEDROCK_DATA_SOURCE_ID": data_source_id,
            "BEDROCK_GENERATION_MODEL_ID": generation_model_id,
            "VECTOR_INDEX_ARN": vector_index_arn,
        }
        qa_lambda = lambda_.Function(
            self,
            "StudyBotQaLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="qa_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(60),
            memory_size=512,
            environment=ai_lambda_environment,
        )
        summary_lambda = lambda_.Function(
            self,
            "StudyBotSummaryLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="summary_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(60),
            memory_size=512,
            environment=ai_lambda_environment,
        )
        quiz_lambda = lambda_.Function(
            self,
            "StudyBotQuizLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="quiz_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(60),
            memory_size=512,
            environment=ai_lambda_environment,
        )

        process_pdf_lambda = lambda_.Function(
            self,
            "ProcessPdfLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="process_pdf_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.minutes(5),
            memory_size=1024,
            environment={
                "DOCUMENTS_TABLE": documents_table.table_name,
                "UPLOADS_BUCKET_NAME": uploads_bucket_name,
                "BEDROCK_KNOWLEDGE_BASE_ID": knowledge_base_id,
                "BEDROCK_DATA_SOURCE_ID": data_source_id,
                "KB_PROCESSED_PREFIX": "documents/processed",
                "USE_TEXTRACT_FALLBACK": "true",
            },
        )

        documents_table.grant_read_write_data(api_lambda)
        documents_table.grant_read_write_data(qa_lambda)
        documents_table.grant_read_write_data(summary_lambda)
        documents_table.grant_read_write_data(quiz_lambda)
        documents_table.grant_read_write_data(process_pdf_lambda)
        uploads_bucket.grant_put(api_lambda)
        uploads_bucket.grant_read_write(process_pdf_lambda)

        api_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:StartIngestionJob",
                    "bedrock:GetIngestionJob",
                ],
                resources=[kb_arn, data_source_arn],
            )
        )
        for ai_lambda in [qa_lambda, summary_lambda, quiz_lambda]:
            ai_lambda.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["bedrock:Retrieve"],
                    resources=[kb_arn],
                )
            )
            ai_lambda.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["bedrock:InvokeModel"],
                    resources=[generation_model_arn, generation_profile_arn],
                )
            )
        process_pdf_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:StartIngestionJob", "bedrock:GetIngestionJob"],
                resources=[kb_arn, data_source_arn],
            )
        )
        process_pdf_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "textract:StartDocumentTextDetection",
                    "textract:GetDocumentTextDetection",
                ],
                resources=["*"],
            )
        )

        for suffix in [".pdf", ".docx", ".md", ".markdown", ".txt", ".pptx", ".vtt"]:
            uploads_bucket.add_event_notification(
                s3.EventType.OBJECT_CREATED,
                s3n.LambdaDestination(process_pdf_lambda),
                s3.NotificationKeyFilter(prefix="documents/raw/", suffix=suffix),
            )

        http_api = apigatewayv2.HttpApi(
            self,
            "StudyBotHttpApi",
            api_name="studybot-api",
            cors_preflight=apigatewayv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_headers=["Content-Type", "Authorization", "X-User-Id", "X-Session-Id"],
                allow_methods=[
                    apigatewayv2.CorsHttpMethod.GET,
                    apigatewayv2.CorsHttpMethod.POST,
                    apigatewayv2.CorsHttpMethod.DELETE,
                    apigatewayv2.CorsHttpMethod.OPTIONS,
                ],
            ),
        )
        api_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotApiLambdaIntegration",
            api_lambda,
        )
        qa_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotQaLambdaIntegration",
            qa_lambda,
        )
        summary_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotSummaryLambdaIntegration",
            summary_lambda,
        )
        quiz_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotQuizLambdaIntegration",
            quiz_lambda,
        )
        http_api.add_routes(
            path="/ask",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=qa_integration,
        )
        http_api.add_routes(
            path="/summary",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=summary_integration,
        )
        http_api.add_routes(
            path="/quiz",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=quiz_integration,
        )
        http_api.add_routes(
            path="/{proxy+}",
            methods=[apigatewayv2.HttpMethod.ANY],
            integration=api_integration,
        )
        http_api.add_routes(
            path="/",
            methods=[apigatewayv2.HttpMethod.ANY],
            integration=api_integration,
        )

        CfnOutput(self, "UploadsBucketName", value=uploads_bucket.bucket_name)
        CfnOutput(self, "DocumentsTableName", value=documents_table.table_name)
        CfnOutput(self, "VectorIndexArn", value=vector_index_arn)
        CfnOutput(self, "KnowledgeBaseId", value=knowledge_base_id)
        CfnOutput(self, "DataSourceId", value=data_source_id)
        CfnOutput(self, "HttpApiUrl", value=http_api.api_endpoint)
        CfnOutput(self, "ApiLambdaName", value=api_lambda.function_name)
        CfnOutput(self, "ProcessPdfLambdaName", value=process_pdf_lambda.function_name)
        CfnOutput(self, "QaLambdaName", value=qa_lambda.function_name)
        CfnOutput(self, "SummaryLambdaName", value=summary_lambda.function_name)
        CfnOutput(self, "QuizLambdaName", value=quiz_lambda.function_name)
