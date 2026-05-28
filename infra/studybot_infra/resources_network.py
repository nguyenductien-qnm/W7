from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from .resource_types import NetworkResources


def create_network_resources(scope: Construct) -> NetworkResources:
    stack = Stack.of(scope)

    studybot_vpc = ec2.Vpc(
        scope,
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
        scope,
        "StudyBotLambdaSecurityGroup",
        vpc=studybot_vpc,
        description="Security group for StudyBot Lambdas in private subnets",
        allow_all_outbound=True,
    )

    endpoint_sg = ec2.SecurityGroup(
        scope,
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
            scope,
            logical_id,
            vpc=studybot_vpc,
            service=ec2.InterfaceVpcEndpointService(service_name, 443),
            subnets=isolated_subnets,
            security_groups=[endpoint_sg],
            private_dns_enabled=True,
        )

    add_interface_endpoint(
        "StudyBotBedrockRuntimeEndpoint",
        f"com.amazonaws.{stack.region}.bedrock-runtime",
    )
    add_interface_endpoint(
        "StudyBotBedrockAgentRuntimeEndpoint",
        f"com.amazonaws.{stack.region}.bedrock-agent-runtime",
    )
    add_interface_endpoint(
        "StudyBotBedrockAgentEndpoint",
        f"com.amazonaws.{stack.region}.bedrock-agent",
    )
    add_interface_endpoint(
        "StudyBotTextractEndpoint",
        f"com.amazonaws.{stack.region}.textract",
    )

    return NetworkResources(
        vpc=studybot_vpc,
        lambda_sg=lambda_sg,
        endpoint_sg=endpoint_sg,
        lambda_network_config=lambda_network_config,
    )
