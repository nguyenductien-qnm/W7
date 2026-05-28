from aws_cdk import aws_route53 as route53
from constructs import Construct

from .resource_types import DomainResources


def create_domain_resources(scope: Construct, root_domain_name: str) -> DomainResources:
    hosted_zone = route53.HostedZone.from_lookup(
        scope,
        "StudyBotHostedZone",
        domain_name=root_domain_name,
    )
    return DomainResources(hosted_zone=hosted_zone)
