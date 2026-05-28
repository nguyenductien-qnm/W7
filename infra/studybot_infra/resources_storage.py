from aws_cdk import RemovalPolicy
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from constructs import Construct

from .resource_types import StorageResources


def create_storage_resources(scope: Construct, root_domain_name: str) -> StorageResources:
    uploads_bucket = s3.Bucket(
        scope,
        "StudyBotUploads",
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        encryption=s3.BucketEncryption.S3_MANAGED,
        enforce_ssl=True,
        cors=[
            s3.CorsRule(
                allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.GET, s3.HttpMethods.HEAD],
                allowed_origins=[
                    f"https://{root_domain_name}",
                    f"https://www.{root_domain_name}",
                ],
                allowed_headers=["*"],
                exposed_headers=["ETag"],
                max_age=3000,
            )
        ],
        auto_delete_objects=True,
        removal_policy=RemovalPolicy.DESTROY,
    )
    documents_table = dynamodb.Table(
        scope,
        "StudyBotDocuments",
        partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
        sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
        billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        removal_policy=RemovalPolicy.DESTROY,
    )
    frontend_bucket = s3.Bucket(
        scope,
        "StudyBotFrontendBucket",
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        encryption=s3.BucketEncryption.S3_MANAGED,
        versioned=False,
        enforce_ssl=True,
    )
    return StorageResources(
        uploads_bucket=uploads_bucket,
        documents_table=documents_table,
        frontend_bucket=frontend_bucket,
    )
