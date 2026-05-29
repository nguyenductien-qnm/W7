from aws_cdk import CfnCondition, CfnOutput, CfnParameter, Fn, Stack, Tags
from constructs import Construct

from .config import (
    API_SUBDOMAIN,
    EMBEDDING_MODEL_ID,
    GENERATION_MODEL_ID,
    ROOT_DOMAIN_NAME,
)
from .resources_agentcore import create_agentcore_resources
from .resources_api import create_api_resources
from .resources_domain import create_domain_resources
from .resources_frontend import create_frontend_resources
from .resources_kb import create_knowledge_base_resources
from .resources_lambda import create_lambda_resources
from .resources_network import create_network_resources
from .resources_observability import create_observability_resources
from .resources_outputs import create_outputs
from .resources_permissions import apply_lambda_permissions
from .resources_storage import create_storage_resources


class StudyBotInfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        tag_options = {"exclude_resource_types": ["AWS::CloudFormation::CustomResource"]}
        Tags.of(self).add("Project", "W7Capstone", **tag_options)
        Tags.of(self).add("Team", "G11", **tag_options)
        Tags.of(self).add("Owner", "DinhDanhNam", **tag_options)
        Tags.of(self).add("Environment", "hackathon", **tag_options)

        root_domain_name = ROOT_DOMAIN_NAME
        api_domain_name = f"{API_SUBDOMAIN}.{root_domain_name}"
        generation_model_id = GENERATION_MODEL_ID
        embedding_model_arn = (
            f"arn:{self.partition}:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL_ID}"
        )
        generation_profile_arn = (
            f"arn:{self.partition}:bedrock:*::foundation-model/amazon.nova-2-lite-v1:0"
        )
        generation_model_arn = (
            f"arn:{self.partition}:bedrock:{self.region}:{self.account}:"
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
        has_agentcore_memory_id = CfnCondition(
            self,
            "HasAgentCoreMemoryId",
            expression=Fn.condition_not(Fn.condition_equals(agentcore_memory_id.value_as_string, "")),
        )

        storage = create_storage_resources(self, root_domain_name=root_domain_name)
        kb = create_knowledge_base_resources(
            self,
            uploads_bucket=storage.uploads_bucket,
            embedding_model_arn=embedding_model_arn,
        )
        domain = create_domain_resources(self, root_domain_name=root_domain_name)
        network = create_network_resources(self)
        lambdas = create_lambda_resources(
            self,
            network=network,
            storage=storage,
            kb=kb,
            generation_model_id=generation_model_id,
            agentcore_memory_id=agentcore_memory_id,
            agentcore_memory_strategy_id=agentcore_memory_strategy_id,
        )
        apply_lambda_permissions(
            self,
            storage=storage,
            kb=kb,
            lambdas=lambdas,
            generation_model_arn=generation_model_arn,
            generation_profile_arn=generation_profile_arn,
            agentcore_memory_id=agentcore_memory_id,
            has_agentcore_memory_id=has_agentcore_memory_id,
        )
        api = create_api_resources(
            self,
            domain=domain,
            root_domain_name=root_domain_name,
            api_domain_name=api_domain_name,
            lambdas=lambdas,
        )
        frontend = create_frontend_resources(
            self,
            storage=storage,
            domain=domain,
            root_domain_name=root_domain_name,
        )
        agentcore = create_agentcore_resources(self, lambdas=lambdas)
        observability = create_observability_resources(self, api=api, lambdas=lambdas)

        create_outputs(
            self,
            storage=storage,
            kb=kb,
            api=api,
            frontend=frontend,
            lambdas=lambdas,
            observability=observability,
            agentcore=agentcore,
            root_domain_name=root_domain_name,
        )
        CfnOutput(self, "VpcId", value=network.vpc.vpc_id)
