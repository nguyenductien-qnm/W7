from aws_cdk import (
    CfnResource,
    CfnOutput,
    CfnParameter,
    Duration,
    ILocalBundling,
    Stack,
)
from aws_cdk import aws_apigatewayv2 as apigatewayv2
from aws_cdk import aws_apigatewayv2_integrations as apigatewayv2_integrations
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as route53_targets
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_s3_notifications as s3n
from constructs import Construct
from pathlib import Path
import jsii
import shutil


@jsii.implements(ILocalBundling)
class ReuseBackendBundle:
    def __init__(self, backend_src_path: str) -> None:
        self.backend_src_path = Path(backend_src_path)

    def try_bundle(self, output_dir: str, *_args, **_kwargs) -> bool:
        output_path = Path(output_dir)
        cdk_out = output_path.parent
        requirements = (self.backend_src_path / "requirements.txt").read_text(encoding="utf-8")
        candidates = [
            path
            for path in cdk_out.glob("asset.*")
            if path.is_dir()
            and not path.name.endswith("-building")
            and (path / "requirements.txt").exists()
            and (path / "requirements.txt").read_text(encoding="utf-8") == requirements
            and (path / "boto3").exists()
        ]
        if not candidates:
            return False
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        shutil.copytree(candidates[0], output_path, dirs_exist_ok=True)
        for source in self.backend_src_path.iterdir():
            target = output_path / source.name
            if source.name in {".env", "__pycache__"}:
                continue
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
        for pycache in output_path.rglob("__pycache__"):
            shutil.rmtree(pycache, ignore_errors=True)
        env_file = output_path / ".env"
        if env_file.exists():
            env_file.unlink()
        return True


class StudyBotInfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        uploads_bucket_name = "studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk"
        documents_table_name = "StudyBotDocuments"
        knowledge_base_role_name = "StudyBotBedrockStack-KnowledgeBaseRoleA2B317B9-UycR9VjqexH0"
        root_domain_name = "nguyenductien.cloud"
        api_domain_name = f"api.{root_domain_name}"
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
        agentcore_memory_id = CfnParameter(
            self,
            "AgentCoreMemoryId",
            type="String",
            default="",
            description="Optional Bedrock AgentCore Memory id for conversation memory.",
        )
        agentcore_memory_strategy_id = CfnParameter(
            self,
            "AgentCoreMemoryStrategyId",
            type="String",
            default="",
            description="Optional Bedrock AgentCore Memory strategy id for retrieval.",
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
        knowledge_base_role = iam.Role.from_role_name(
            self,
            "StudyBotKnowledgeBaseRole",
            role_name=knowledge_base_role_name,
            mutable=True,
        )
        hosted_zone = route53.HostedZone.from_lookup(
            self,
            "StudyBotHostedZone",
            domain_name=root_domain_name,
        )

        frontend_bucket = s3.Bucket(
            self,
            "StudyBotFrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=False,
            enforce_ssl=True,
        )

        studybot_vpc = ec2.Vpc(
            self,
            "StudyBotVpc",
            nat_gateways=0,
            max_azs=2,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="private-isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        lambda_sg = ec2.SecurityGroup(
            self,
            "StudyBotLambdaSecurityGroup",
            vpc=studybot_vpc,
            description="Security group for StudyBot Lambdas in private subnets",
            allow_all_outbound=True,
        )

        endpoint_sg = ec2.SecurityGroup(
            self,
            "StudyBotEndpointSecurityGroup",
            vpc=studybot_vpc,
            description="Security group for VPC interface endpoints",
            allow_all_outbound=True,
        )
        endpoint_sg.add_ingress_rule(
            lambda_sg,
            ec2.Port.tcp(443),
            "Allow HTTPS from Lambda SG to interface endpoints",
        )

        isolated_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)
        lambda_network_config = {
            "vpc": studybot_vpc,
            "vpc_subnets": isolated_subnets,
            "security_groups": [lambda_sg],
        }

        studybot_vpc.add_gateway_endpoint(
            "StudyBotS3GatewayEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
            subnets=[isolated_subnets],
        )
        studybot_vpc.add_gateway_endpoint(
            "StudyBotDynamoDbGatewayEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB,
            subnets=[isolated_subnets],
        )

        def add_interface_endpoint(logical_id: str, service_name: str):
            return ec2.InterfaceVpcEndpoint(
                self,
                logical_id,
                vpc=studybot_vpc,
                service=ec2.InterfaceVpcEndpointService(service_name, 443),
                subnets=isolated_subnets,
                security_groups=[endpoint_sg],
                private_dns_enabled=True,
            )

        add_interface_endpoint(
            "StudyBotBedrockRuntimeEndpoint",
            f"com.amazonaws.{self.region}.bedrock-runtime",
        )
        add_interface_endpoint(
            "StudyBotBedrockAgentRuntimeEndpoint",
            f"com.amazonaws.{self.region}.bedrock-agent-runtime",
        )
        add_interface_endpoint(
            "StudyBotBedrockAgentEndpoint",
            f"com.amazonaws.{self.region}.bedrock-agent",
        )
        add_interface_endpoint(
            "StudyBotTextractEndpoint",
            f"com.amazonaws.{self.region}.textract",
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

        login_lambda = lambda_.Function(
            self,
            "StudyBotLoginLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="auth.login_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(30),
            memory_size=512,
            **lambda_network_config,
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
        sessions_lambda = lambda_.Function(
            self,
            "StudyBotSessionsLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="session.sessions_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(30),
            memory_size=512,
            **lambda_network_config,
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
        upload_lambda = lambda_.Function(
            self,
            "StudyBotUploadLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="upload.upload_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(30),
            memory_size=512,
            **lambda_network_config,
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
        documents_lambda = lambda_.Function(
            self,
            "StudyBotDocumentsLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="documents.documents_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(30),
            memory_size=512,
            **lambda_network_config,
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
            "UPLOADS_BUCKET_NAME": uploads_bucket_name,
            "AGENTCORE_MEMORY_ID": agentcore_memory_id.value_as_string,
            "AGENTCORE_MEMORY_STRATEGY_ID": agentcore_memory_strategy_id.value_as_string,
        }
        qa_lambda = lambda_.Function(
            self,
            "StudyBotQaLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="qa.qa_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(60),
            memory_size=512,
            **lambda_network_config,
            environment=ai_lambda_environment,
        )
        summary_lambda = lambda_.Function(
            self,
            "StudyBotSummaryLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="summary.summary_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(60),
            memory_size=512,
            **lambda_network_config,
            environment=ai_lambda_environment,
        )
        quiz_lambda = lambda_.Function(
            self,
            "StudyBotQuizLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="quiz.quiz_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(60),
            memory_size=512,
            **lambda_network_config,
            environment=ai_lambda_environment,
        )
        planner_lambda = lambda_.Function(
            self,
            "StudyBotPlannerLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="planner.planner_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(60),
            memory_size=512,
            **lambda_network_config,
            environment=ai_lambda_environment,
        )
        history_lambda = lambda_.Function(
            self,
            "StudyBotHistoryLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="history.history_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.seconds(30),
            memory_size=512,
            **lambda_network_config,
            environment=ai_lambda_environment,
        )

        process_pdf_lambda = lambda_.Function(
            self,
            "ProcessPdfLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="ingestion.process_pdf_lambda.lambda_handler",
            code=backend_lambda_code,
            timeout=Duration.minutes(5),
            memory_size=1024,
            **lambda_network_config,
            environment={
                "DOCUMENTS_TABLE": documents_table.table_name,
                "UPLOADS_BUCKET_NAME": uploads_bucket_name,
                "BEDROCK_KNOWLEDGE_BASE_ID": knowledge_base_id,
                "BEDROCK_DATA_SOURCE_ID": data_source_id,
                "KB_PROCESSED_PREFIX": "processed",
                "USE_TEXTRACT_FALLBACK": "true",
            },
        )

        table_arn = documents_table.table_arn

        def add_ddb_policy(target_lambda: lambda_.Function, actions: list[str]):
            target_lambda.add_to_role_policy(
                iam.PolicyStatement(
                    actions=actions,
                    resources=[table_arn],
                )
            )

        add_ddb_policy(login_lambda, ["dynamodb:GetItem", "dynamodb:Scan"])
        add_ddb_policy(
            sessions_lambda,
            ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:BatchWriteItem"],
        )
        add_ddb_policy(upload_lambda, ["dynamodb:GetItem", "dynamodb:PutItem"])
        add_ddb_policy(documents_lambda, ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"])
        add_ddb_policy(qa_lambda, ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"])
        add_ddb_policy(summary_lambda, ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"])
        add_ddb_policy(quiz_lambda, ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"])
        add_ddb_policy(
            planner_lambda,
            ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:BatchWriteItem"],
        )
        add_ddb_policy(history_lambda, ["dynamodb:Query"])
        add_ddb_policy(process_pdf_lambda, ["dynamodb:GetItem", "dynamodb:PutItem"])

        upload_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"],
                resources=[
                    f"arn:aws:s3:::{uploads_bucket_name}/raw/*",
                    f"arn:aws:s3:::{uploads_bucket_name}/documents/raw/*",
                ],
            )
        )
        summary_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[
                    f"arn:aws:s3:::{uploads_bucket_name}/processed/*",
                    f"arn:aws:s3:::{uploads_bucket_name}/documents/processed/*",
                ],
            )
        )
        process_pdf_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[
                    f"arn:aws:s3:::{uploads_bucket_name}/raw/*",
                    f"arn:aws:s3:::{uploads_bucket_name}/documents/raw/*",
                ],
            )
        )
        process_pdf_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject", "s3:DeleteObject"],
                resources=[
                    f"arn:aws:s3:::{uploads_bucket_name}/processed/*",
                    f"arn:aws:s3:::{uploads_bucket_name}/documents/processed/*",
                ],
            )
        )
        knowledge_base_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[
                    f"arn:aws:s3:::{uploads_bucket_name}/processed/*",
                    f"arn:aws:s3:::{uploads_bucket_name}/documents/processed/*",
                ],
            )
        )
        process_pdf_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[f"arn:aws:s3:::{uploads_bucket_name}"],
            )
        )
        documents_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:GetIngestionJob",
                ],
                resources=[kb_arn, data_source_arn],
            )
        )
        for ai_lambda in [qa_lambda, summary_lambda, quiz_lambda, planner_lambda]:
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
        for memory_lambda in [qa_lambda, planner_lambda]:
            memory_lambda.add_to_role_policy(
                iam.PolicyStatement(
                    actions=[
                        "bedrock-agentcore:CreateEvent",
                        "bedrock-agentcore:RetrieveMemoryRecords",
                    ],
                    resources=["*"],
                )
            )
        process_pdf_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:StartIngestionJob",
                    "bedrock:GetIngestionJob",
                    "bedrock:ListIngestionJobs",
                ],
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
                s3.NotificationKeyFilter(prefix="raw/", suffix=suffix),
            )
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
                    apigatewayv2.CorsHttpMethod.PUT,
                    apigatewayv2.CorsHttpMethod.PATCH,
                    apigatewayv2.CorsHttpMethod.DELETE,
                    apigatewayv2.CorsHttpMethod.OPTIONS,
                ],
            ),
        )
        login_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotLoginLambdaIntegration",
            login_lambda,
        )
        sessions_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotSessionsLambdaIntegration",
            sessions_lambda,
        )
        upload_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotUploadLambdaIntegration",
            upload_lambda,
        )
        documents_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotDocumentsLambdaIntegration",
            documents_lambda,
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
        planner_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotPlannerLambdaIntegration",
            planner_lambda,
        )
        history_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotHistoryLambdaIntegration",
            history_lambda,
        )
        http_api.add_routes(
            path="/login",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=login_integration,
        )
        http_api.add_routes(
            path="/session/create",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=sessions_integration,
        )
        http_api.add_routes(
            path="/session/list",
            methods=[apigatewayv2.HttpMethod.GET],
            integration=sessions_integration,
        )
        http_api.add_routes(
            path="/session/{session_id}",
            methods=[apigatewayv2.HttpMethod.DELETE],
            integration=sessions_integration,
        )
        http_api.add_routes(
            path="/documents/upload-url",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=upload_integration,
        )
        http_api.add_routes(
            path="/upload/presign",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=upload_integration,
        )
        http_api.add_routes(
            path="/upload",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=upload_integration,
        )
        http_api.add_routes(
            path="/documents/{doc_id}/complete",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=upload_integration,
        )
        http_api.add_routes(
            path="/docs/list",
            methods=[apigatewayv2.HttpMethod.GET],
            integration=documents_integration,
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
            path="/planner",
            methods=[apigatewayv2.HttpMethod.GET, apigatewayv2.HttpMethod.POST],
            integration=planner_integration,
        )
        http_api.add_routes(
            path="/planner/clarify",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=planner_integration,
        )
        http_api.add_routes(
            path="/planner/{plan_id}",
            methods=[
                apigatewayv2.HttpMethod.GET,
                apigatewayv2.HttpMethod.PUT,
                apigatewayv2.HttpMethod.PATCH,
                apigatewayv2.HttpMethod.DELETE,
            ],
            integration=planner_integration,
        )
        http_api.add_routes(
            path="/planner/{plan_id}/recommend-docs",
            methods=[apigatewayv2.HttpMethod.POST],
            integration=planner_integration,
        )
        http_api.add_routes(
            path="/history",
            methods=[apigatewayv2.HttpMethod.GET],
            integration=history_integration,
        )
        http_api.add_routes(
            path="/dashboard",
            methods=[apigatewayv2.HttpMethod.GET],
            integration=history_integration,
        )

        api_certificate = acm.Certificate(
            self,
            "StudyBotApiCertificate",
            domain_name=api_domain_name,
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )
        api_custom_domain = apigatewayv2.DomainName(
            self,
            "StudyBotApiCustomDomain",
            domain_name=api_domain_name,
            certificate=api_certificate,
        )
        apigatewayv2.ApiMapping(
            self,
            "StudyBotApiMapping",
            api=http_api,
            domain_name=api_custom_domain,
            stage=http_api.default_stage,
        )
        route53.ARecord(
            self,
            "StudyBotApiAliasRecord",
            zone=hosted_zone,
            record_name="api",
            target=route53.RecordTarget.from_alias(
                route53_targets.ApiGatewayv2DomainProperties(
                    api_custom_domain.regional_domain_name,
                    api_custom_domain.regional_hosted_zone_id,
                )
            ),
        )
        route53.AaaaRecord(
            self,
            "StudyBotApiAliasRecordIpv6",
            zone=hosted_zone,
            record_name="api",
            target=route53.RecordTarget.from_alias(
                route53_targets.ApiGatewayv2DomainProperties(
                    api_custom_domain.regional_domain_name,
                    api_custom_domain.regional_hosted_zone_id,
                )
            ),
        )

        frontend_certificate = acm.DnsValidatedCertificate(
            self,
            "StudyBotFrontendCertificate",
            hosted_zone=hosted_zone,
            domain_name=root_domain_name,
            subject_alternative_names=[f"www.{root_domain_name}"],
            region="us-east-1",
        )
        frontend_distribution = cloudfront.Distribution(
            self,
            "StudyBotFrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(frontend_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            default_root_object="index.html",
            domain_names=[root_domain_name, f"www.{root_domain_name}"],
            certificate=frontend_certificate,
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(30),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(30),
                ),
            ],
        )

        frontend_dist_path = str(Path(__file__).resolve().parents[2] / "FE" / "dist")
        s3deploy.BucketDeployment(
            self,
            "StudyBotFrontendDeployment",
            destination_bucket=frontend_bucket,
            sources=[s3deploy.Source.asset(frontend_dist_path)],
            distribution=frontend_distribution,
            distribution_paths=["/*"],
            prune=True,
            retain_on_delete=False,
        )
        route53.ARecord(
            self,
            "StudyBotFrontendAliasRootA",
            zone=hosted_zone,
            record_name=root_domain_name,
            target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(frontend_distribution)),
        )
        route53.AaaaRecord(
            self,
            "StudyBotFrontendAliasRootAAAA",
            zone=hosted_zone,
            record_name=root_domain_name,
            target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(frontend_distribution)),
        )
        route53.ARecord(
            self,
            "StudyBotFrontendAliasWwwA",
            zone=hosted_zone,
            record_name=f"www.{root_domain_name}",
            target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(frontend_distribution)),
        )
        route53.AaaaRecord(
            self,
            "StudyBotFrontendAliasWwwAAAA",
            zone=hosted_zone,
            record_name=f"www.{root_domain_name}",
            target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(frontend_distribution)),
        )

        gateway_role = iam.Role(
            self,
            "StudyBotAgentCoreGatewayRole",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        for target_lambda in [qa_lambda, summary_lambda, quiz_lambda, planner_lambda, history_lambda]:
            target_lambda.grant_invoke(gateway_role)
            target_lambda.add_permission(
                f"AgentCoreInvoke{target_lambda.node.id}",
                principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
                action="lambda:InvokeFunction",
            )

        agentcore_gateway = CfnResource(
            self,
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

        def string_schema(description):
            return {"Type": "string", "Description": description}

        def array_string_schema(description):
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

        def add_agentcore_lambda_target(logical_id, name, description, fn, tools):
            return CfnResource(
                self,
                logical_id,
                type="AWS::BedrockAgentCore::GatewayTarget",
                properties={
                    "Name": name,
                    "Description": description,
                    "GatewayIdentifier": agentcore_gateway.ref,
                    "CredentialProviderConfigurations": [
                        {"CredentialProviderType": "GATEWAY_IAM_ROLE"}
                    ],
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
            qa_lambda,
            [("ask_documents", "Answer questions from selected documents.")],
        )
        add_agentcore_lambda_target(
            "StudyBotSummaryToolsTarget",
            "studybot-summary-tools",
            "Document summary tools.",
            summary_lambda,
            [("summarize_documents", "Summarize selected documents.")],
        )
        add_agentcore_lambda_target(
            "StudyBotQuizToolsTarget",
            "studybot-quiz-tools",
            "Quiz and flashcard generation tools.",
            quiz_lambda,
            [
                ("generate_quiz", "Generate quiz questions from selected documents."),
                ("generate_flashcards", "Generate flashcards from selected documents."),
            ],
        )
        add_agentcore_lambda_target(
            "StudyBotPlannerToolsTarget",
            "studybot-planner-tools",
            "Exam planning tools.",
            planner_lambda,
            [
                ("create_exam_plan", "Create a dated study plan before an exam."),
                ("recommend_exam_plan_documents", "Recommend ready session documents relevant to a saved exam plan."),
            ],
        )
        add_agentcore_lambda_target(
            "StudyBotHistoryToolsTarget",
            "studybot-history-tools",
            "Session history tools.",
            history_lambda,
            [("get_history", "Get UI history for the active study session.")],
        )

        dashboard = cloudwatch.Dashboard(
            self,
            "StudyBotOperationsDashboard",
            dashboard_name="StudyBot-W7-Operations",
        )
        lambda_functions = [
            upload_lambda,
            process_pdf_lambda,
            qa_lambda,
            summary_lambda,
            quiz_lambda,
            planner_lambda,
            history_lambda,
        ]
        lambda_error_metrics = [fn.metric_errors(period=Duration.minutes(5)) for fn in lambda_functions]
        duration_metrics = [
            process_pdf_lambda.metric_duration(statistic="p95", period=Duration.minutes(5)),
            qa_lambda.metric_duration(statistic="p95", period=Duration.minutes(5)),
        ]
        api_5xx_metric = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="5xx",
            dimensions_map={"ApiId": http_api.api_id, "Stage": "$default"},
            statistic="sum",
            period=Duration.minutes(5),
        )
        ingestion_failure_metric_filter = logs.MetricFilter(
            self,
            "StudyBotIngestionFailureMetricFilter",
            log_group=logs.LogGroup.from_log_group_name(
                self,
                "ProcessPdfLambdaLogGroup",
                f"/aws/lambda/{process_pdf_lambda.function_name}",
            ),
            metric_namespace="StudyBot/W7",
            metric_name="IngestionFailures",
            filter_pattern=logs.FilterPattern.any_term("FAILED", "failure", "error", "Exception"),
            metric_value="1",
            default_value=0,
        )
        ingestion_failure_metric = ingestion_failure_metric_filter.metric(
            statistic="sum",
            period=Duration.minutes(5),
        )
        cloudwatch.Alarm(
            self,
            "StudyBotApi5xxAlarm",
            metric=api_5xx_metric,
            threshold=1,
            evaluation_periods=1,
            alarm_description="Sensitive W7 demo alarm: API Gateway returned at least one 5XX in 5 minutes.",
        )
        for fn in lambda_functions:
            cloudwatch.Alarm(
                self,
                f"{fn.node.id}ErrorsAlarm",
                metric=fn.metric_errors(period=Duration.minutes(5)),
                threshold=1,
                evaluation_periods=1,
                alarm_description=f"Sensitive W7 demo alarm: {fn.function_name} reported an error.",
            )
        cloudwatch.Alarm(
            self,
            "StudyBotQaDurationAlarm",
            metric=qa_lambda.metric_duration(statistic="p95", period=Duration.minutes(5)),
            threshold=45000,
            evaluation_periods=1,
            alarm_description="Sensitive W7 demo alarm: Q&A p95 duration exceeded 45 seconds.",
        )
        cloudwatch.Alarm(
            self,
            "StudyBotIngestionDurationAlarm",
            metric=process_pdf_lambda.metric_duration(statistic="p95", period=Duration.minutes(5)),
            threshold=240000,
            evaluation_periods=1,
            alarm_description="Sensitive W7 demo alarm: ingestion p95 duration exceeded 4 minutes.",
        )
        cloudwatch.Alarm(
            self,
            "StudyBotIngestionFailureAlarm",
            metric=ingestion_failure_metric,
            threshold=1,
            evaluation_periods=1,
            alarm_description="Sensitive W7 demo alarm: ingestion log output contained a failure signal.",
        )
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="API Gateway 5XX",
                left=[api_5xx_metric],
                width=12,
            ),
            cloudwatch.GraphWidget(
                title="Lambda Errors",
                left=lambda_error_metrics,
                width=12,
            ),
        )
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Ingestion and Q&A p95 Duration",
                left=duration_metrics,
                width=12,
            ),
            cloudwatch.GraphWidget(
                title="Ingestion Failure Log Signals",
                left=[ingestion_failure_metric],
                width=12,
            ),
        )

        CfnOutput(self, "UploadsBucketName", value=uploads_bucket.bucket_name)
        CfnOutput(self, "DocumentsTableName", value=documents_table.table_name)
        CfnOutput(self, "VectorIndexArn", value=vector_index_arn)
        CfnOutput(self, "KnowledgeBaseId", value=knowledge_base_id)
        CfnOutput(self, "DataSourceId", value=data_source_id)
        CfnOutput(self, "HttpApiUrl", value=http_api.api_endpoint)
        CfnOutput(self, "ApiCustomDomain", value=api_domain_name)
        CfnOutput(self, "FrontendBucketName", value=frontend_bucket.bucket_name)
        CfnOutput(self, "FrontendCloudFrontDomain", value=frontend_distribution.domain_name)
        CfnOutput(self, "FrontendCustomDomain", value=root_domain_name)
        CfnOutput(self, "LoginLambdaName", value=login_lambda.function_name)
        CfnOutput(self, "SessionsLambdaName", value=sessions_lambda.function_name)
        CfnOutput(self, "UploadLambdaName", value=upload_lambda.function_name)
        CfnOutput(self, "DocumentsLambdaName", value=documents_lambda.function_name)
        CfnOutput(self, "ProcessPdfLambdaName", value=process_pdf_lambda.function_name)
        CfnOutput(self, "QaLambdaName", value=qa_lambda.function_name)
        CfnOutput(self, "SummaryLambdaName", value=summary_lambda.function_name)
        CfnOutput(self, "QuizLambdaName", value=quiz_lambda.function_name)
        CfnOutput(self, "PlannerLambdaName", value=planner_lambda.function_name)
        CfnOutput(self, "HistoryLambdaName", value=history_lambda.function_name)
        CfnOutput(self, "OperationsDashboardName", value=dashboard.dashboard_name)
        CfnOutput(self, "IngestionFailureMetricName", value="StudyBot/W7/IngestionFailures")
        CfnOutput(self, "AgentCoreGatewayId", value=agentcore_gateway.ref)
        CfnOutput(self, "AgentCoreGatewayUrl", value=agentcore_gateway.get_att("GatewayUrl").to_string())
        CfnOutput(self, "VpcId", value=studybot_vpc.vpc_id)
