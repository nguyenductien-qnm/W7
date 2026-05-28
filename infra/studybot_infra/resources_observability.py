from aws_cdk import Duration
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_logs as logs
from constructs import Construct

from .resource_types import ApiResources, LambdaResources, ObservabilityResources


def create_observability_resources(
    scope: Construct,
    *,
    api: ApiResources,
    lambdas: LambdaResources,
) -> ObservabilityResources:
    dashboard = cloudwatch.Dashboard(
        scope,
        "StudyBotOperationsDashboard",
        dashboard_name="StudyBot-W7-Operations",
    )
    lambda_functions = [
        lambdas.upload_lambda,
        lambdas.process_pdf_lambda,
        lambdas.qa_lambda,
        lambdas.summary_lambda,
        lambdas.quiz_lambda,
        lambdas.planner_lambda,
        lambdas.history_lambda,
    ]
    lambda_error_metrics = [fn.metric_errors(period=Duration.minutes(5)) for fn in lambda_functions]
    duration_metrics = [
        lambdas.process_pdf_lambda.metric_duration(statistic="p95", period=Duration.minutes(5)),
        lambdas.qa_lambda.metric_duration(statistic="p95", period=Duration.minutes(5)),
    ]
    api_5xx_metric = cloudwatch.Metric(
        namespace="AWS/ApiGateway",
        metric_name="5xx",
        dimensions_map={"ApiId": api.http_api.api_id, "Stage": "$default"},
        statistic="sum",
        period=Duration.minutes(5),
    )
    ingestion_failure_metric_filter = logs.MetricFilter(
        scope,
        "StudyBotIngestionFailureMetricFilter",
        log_group=logs.LogGroup.from_log_group_name(
            scope,
            "ProcessPdfLambdaLogGroup",
            f"/aws/lambda/{lambdas.process_pdf_lambda.function_name}",
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
        scope,
        "StudyBotApi5xxAlarm",
        metric=api_5xx_metric,
        threshold=1,
        evaluation_periods=1,
        alarm_description="Sensitive W7 demo alarm: API Gateway returned at least one 5XX in 5 minutes.",
    )
    for fn in lambda_functions:
        cloudwatch.Alarm(
            scope,
            f"{fn.node.id}ErrorsAlarm",
            metric=fn.metric_errors(period=Duration.minutes(5)),
            threshold=1,
            evaluation_periods=1,
            alarm_description=f"Sensitive W7 demo alarm: {fn.function_name} reported an error.",
        )
    cloudwatch.Alarm(
        scope,
        "StudyBotQaDurationAlarm",
        metric=lambdas.qa_lambda.metric_duration(statistic="p95", period=Duration.minutes(5)),
        threshold=45000,
        evaluation_periods=1,
        alarm_description="Sensitive W7 demo alarm: Q&A p95 duration exceeded 45 seconds.",
    )
    cloudwatch.Alarm(
        scope,
        "StudyBotIngestionDurationAlarm",
        metric=lambdas.process_pdf_lambda.metric_duration(statistic="p95", period=Duration.minutes(5)),
        threshold=240000,
        evaluation_periods=1,
        alarm_description="Sensitive W7 demo alarm: ingestion p95 duration exceeded 4 minutes.",
    )
    cloudwatch.Alarm(
        scope,
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
    return ObservabilityResources(dashboard=dashboard)
