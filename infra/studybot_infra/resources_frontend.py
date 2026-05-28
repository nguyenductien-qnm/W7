from pathlib import Path

from aws_cdk import Duration
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as route53_targets
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from .resource_types import DomainResources, FrontendResources, StorageResources


def create_frontend_resources(
    scope: Construct,
    *,
    storage: StorageResources,
    domain: DomainResources,
    root_domain_name: str,
) -> FrontendResources:
    frontend_certificate = acm.DnsValidatedCertificate(
        scope,
        "StudyBotFrontendCertificate",
        hosted_zone=domain.hosted_zone,
        domain_name=root_domain_name,
        subject_alternative_names=[f"www.{root_domain_name}"],
        region="us-east-1",
    )
    frontend_distribution = cloudfront.Distribution(
        scope,
        "StudyBotFrontendDistribution",
        default_behavior=cloudfront.BehaviorOptions(
            origin=origins.S3Origin(storage.frontend_bucket),
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
        scope,
        "StudyBotFrontendDeployment",
        destination_bucket=storage.frontend_bucket,
        sources=[s3deploy.Source.asset(frontend_dist_path)],
        distribution=frontend_distribution,
        distribution_paths=["/*"],
        prune=True,
        retain_on_delete=False,
    )
    route53.ARecord(
        scope,
        "StudyBotFrontendAliasRootA",
        zone=domain.hosted_zone,
        record_name=root_domain_name,
        target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(frontend_distribution)),
    )
    route53.AaaaRecord(
        scope,
        "StudyBotFrontendAliasRootAAAA",
        zone=domain.hosted_zone,
        record_name=root_domain_name,
        target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(frontend_distribution)),
    )
    route53.ARecord(
        scope,
        "StudyBotFrontendAliasWwwA",
        zone=domain.hosted_zone,
        record_name=f"www.{root_domain_name}",
        target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(frontend_distribution)),
    )
    route53.AaaaRecord(
        scope,
        "StudyBotFrontendAliasWwwAAAA",
        zone=domain.hosted_zone,
        record_name=f"www.{root_domain_name}",
        target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(frontend_distribution)),
    )
    return FrontendResources(distribution=frontend_distribution)
