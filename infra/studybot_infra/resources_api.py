from aws_cdk import aws_apigatewayv2 as apigatewayv2
from aws_cdk import aws_apigatewayv2_integrations as apigatewayv2_integrations
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as route53_targets
from constructs import Construct

from .resource_types import ApiResources, DomainResources, LambdaResources


def create_api_resources(
    scope: Construct,
    *,
    domain: DomainResources,
    root_domain_name: str,
    api_domain_name: str,
    lambdas: LambdaResources,
) -> ApiResources:
    http_api = apigatewayv2.HttpApi(
        scope,
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

    integrations = {
        "login": apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotLoginLambdaIntegration", lambdas.login_lambda
        ),
        "sessions": apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotSessionsLambdaIntegration", lambdas.sessions_lambda
        ),
        "upload": apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotUploadLambdaIntegration", lambdas.upload_lambda
        ),
        "documents": apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotDocumentsLambdaIntegration", lambdas.documents_lambda
        ),
        "qa": apigatewayv2_integrations.HttpLambdaIntegration("StudyBotQaLambdaIntegration", lambdas.qa_lambda),
        "summary": apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotSummaryLambdaIntegration", lambdas.summary_lambda
        ),
        "quiz": apigatewayv2_integrations.HttpLambdaIntegration("StudyBotQuizLambdaIntegration", lambdas.quiz_lambda),
        "planner": apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotPlannerLambdaIntegration", lambdas.planner_lambda
        ),
        "history": apigatewayv2_integrations.HttpLambdaIntegration(
            "StudyBotHistoryLambdaIntegration", lambdas.history_lambda
        ),
    }

    http_api.add_routes(
        path="/login",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["login"],
    )
    http_api.add_routes(
        path="/session/create",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["sessions"],
    )
    http_api.add_routes(
        path="/session/list",
        methods=[apigatewayv2.HttpMethod.GET],
        integration=integrations["sessions"],
    )
    http_api.add_routes(
        path="/session/{session_id}",
        methods=[apigatewayv2.HttpMethod.DELETE],
        integration=integrations["sessions"],
    )
    http_api.add_routes(
        path="/documents/upload-url",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["upload"],
    )
    http_api.add_routes(
        path="/upload/presign",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["upload"],
    )
    http_api.add_routes(
        path="/upload",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["upload"],
    )
    http_api.add_routes(
        path="/documents/{doc_id}/complete",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["upload"],
    )
    http_api.add_routes(
        path="/docs/list",
        methods=[apigatewayv2.HttpMethod.GET],
        integration=integrations["documents"],
    )
    http_api.add_routes(
        path="/ask",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["qa"],
    )
    http_api.add_routes(
        path="/summary",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["summary"],
    )
    http_api.add_routes(
        path="/quiz",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["quiz"],
    )
    http_api.add_routes(
        path="/planner",
        methods=[apigatewayv2.HttpMethod.GET, apigatewayv2.HttpMethod.POST],
        integration=integrations["planner"],
    )
    http_api.add_routes(
        path="/planner/clarify",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["planner"],
    )
    http_api.add_routes(
        path="/planner/{plan_id}",
        methods=[
            apigatewayv2.HttpMethod.GET,
            apigatewayv2.HttpMethod.PUT,
            apigatewayv2.HttpMethod.PATCH,
            apigatewayv2.HttpMethod.DELETE,
        ],
        integration=integrations["planner"],
    )
    http_api.add_routes(
        path="/planner/{plan_id}/recommend-docs",
        methods=[apigatewayv2.HttpMethod.POST],
        integration=integrations["planner"],
    )
    http_api.add_routes(
        path="/history",
        methods=[apigatewayv2.HttpMethod.GET],
        integration=integrations["history"],
    )
    http_api.add_routes(
        path="/dashboard",
        methods=[apigatewayv2.HttpMethod.GET],
        integration=integrations["history"],
    )

    default_http_stage = http_api.default_stage
    default_http_stage_cfn = default_http_stage.node.default_child
    if not isinstance(default_http_stage_cfn, apigatewayv2.CfnStage):
        raise ValueError("Expected HttpApi default stage to synthesize as CfnStage")
    default_http_stage_cfn.default_route_settings = apigatewayv2.CfnStage.RouteSettingsProperty(
        detailed_metrics_enabled=True,
        throttling_rate_limit=80,
        throttling_burst_limit=160,
    )
    heavy_route_settings = {
        "ThrottlingRateLimit": 20,
        "ThrottlingBurstLimit": 40,
    }
    default_http_stage_cfn.route_settings = {
        "POST /ask": heavy_route_settings,
        "POST /summary": heavy_route_settings,
        "POST /quiz": heavy_route_settings,
        "GET /planner": heavy_route_settings,
        "POST /planner": heavy_route_settings,
        "POST /planner/clarify": heavy_route_settings,
        "GET /planner/{plan_id}": heavy_route_settings,
        "PUT /planner/{plan_id}": heavy_route_settings,
        "PATCH /planner/{plan_id}": heavy_route_settings,
        "DELETE /planner/{plan_id}": heavy_route_settings,
        "POST /planner/{plan_id}/recommend-docs": heavy_route_settings,
    }

    api_certificate = acm.Certificate(
        scope,
        "StudyBotApiCertificate",
        domain_name=api_domain_name,
        validation=acm.CertificateValidation.from_dns(domain.hosted_zone),
    )
    api_custom_domain = apigatewayv2.DomainName(
        scope,
        "StudyBotApiCustomDomain",
        domain_name=api_domain_name,
        certificate=api_certificate,
    )
    apigatewayv2.ApiMapping(
        scope,
        "StudyBotApiMapping",
        api=http_api,
        domain_name=api_custom_domain,
        stage=http_api.default_stage,
    )
    route53.ARecord(
        scope,
        "StudyBotApiAliasRecord",
        zone=domain.hosted_zone,
        record_name="api",
        target=route53.RecordTarget.from_alias(
            route53_targets.ApiGatewayv2DomainProperties(
                api_custom_domain.regional_domain_name,
                api_custom_domain.regional_hosted_zone_id,
            )
        ),
    )
    route53.AaaaRecord(
        scope,
        "StudyBotApiAliasRecordIpv6",
        zone=domain.hosted_zone,
        record_name="api",
        target=route53.RecordTarget.from_alias(
            route53_targets.ApiGatewayv2DomainProperties(
                api_custom_domain.regional_domain_name,
                api_custom_domain.regional_hosted_zone_id,
            )
        ),
    )
    return ApiResources(http_api=http_api, api_domain_name=api_domain_name)
