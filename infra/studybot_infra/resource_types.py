from dataclasses import dataclass

from aws_cdk import CfnResource
from aws_cdk import aws_apigatewayv2 as apigatewayv2
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3vectors as s3vectors


@dataclass
class StorageResources:
    uploads_bucket: s3.Bucket
    documents_table: dynamodb.Table
    frontend_bucket: s3.Bucket


@dataclass
class KnowledgeBaseResources:
    vector_bucket: s3vectors.CfnVectorBucket
    vector_index: s3vectors.CfnIndex
    role: iam.Role
    knowledge_base: bedrock.CfnKnowledgeBase
    data_source: bedrock.CfnDataSource
    kb_arn: str
    data_source_arn: str
    vector_index_arn: str
    knowledge_base_id: str
    data_source_id: str


@dataclass
class NetworkResources:
    vpc: ec2.Vpc
    lambda_sg: ec2.SecurityGroup
    endpoint_sg: ec2.SecurityGroup
    lambda_network_config: dict


@dataclass
class LambdaResources:
    login_lambda: lambda_.Function
    sessions_lambda: lambda_.Function
    upload_lambda: lambda_.Function
    documents_lambda: lambda_.Function
    qa_lambda: lambda_.Function
    summary_lambda: lambda_.Function
    quiz_lambda: lambda_.Function
    planner_lambda: lambda_.Function
    history_lambda: lambda_.Function
    process_pdf_lambda: lambda_.Function


@dataclass
class ApiResources:
    http_api: apigatewayv2.HttpApi
    api_domain_name: str


@dataclass
class FrontendResources:
    distribution: cloudfront.Distribution


@dataclass
class AgentCoreResources:
    gateway: CfnResource


@dataclass
class ObservabilityResources:
    dashboard: cloudwatch.Dashboard


@dataclass
class DomainResources:
    hosted_zone: route53.IHostedZone
