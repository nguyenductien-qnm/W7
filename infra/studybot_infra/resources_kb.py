from aws_cdk import Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3vectors as s3vectors
from constructs import Construct

from .config import KB_DATA_SOURCE_NAME, KB_NAME, KB_VECTOR_INDEX_NAME
from .resource_types import KnowledgeBaseResources


def create_knowledge_base_resources(
    scope: Construct,
    *,
    uploads_bucket: s3.Bucket,
    embedding_model_arn: str,
) -> KnowledgeBaseResources:
    stack = Stack.of(scope)

    knowledge_base_vector_bucket = s3vectors.CfnVectorBucket(
        scope,
        "StudyBotKnowledgeBaseVectorBucket",
    )
    knowledge_base_vector_index = s3vectors.CfnIndex(
        scope,
        "StudyBotKnowledgeBaseVectorIndex",
        vector_bucket_arn=knowledge_base_vector_bucket.attr_vector_bucket_arn,
        data_type="float32",
        dimension=1024,
        distance_metric="cosine",
        index_name=KB_VECTOR_INDEX_NAME,
        metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
            non_filterable_metadata_keys=[
                "AMAZON_BEDROCK_TEXT",
                "AMAZON_BEDROCK_METADATA",
            ]
        ),
    )
    knowledge_base_role = iam.Role(
        scope,
        "StudyBotKnowledgeBaseRole",
        assumed_by=iam.ServicePrincipal(
            "bedrock.amazonaws.com",
            conditions={
                "StringEquals": {"aws:SourceAccount": stack.account},
                "ArnLike": {
                    "aws:SourceArn": (
                        f"arn:{stack.partition}:bedrock:{stack.region}:{stack.account}:knowledge-base/*"
                    )
                },
            },
        ),
        description="Service role for StudyBot Bedrock Knowledge Base.",
    )
    knowledge_base_role.add_to_policy(
        iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[embedding_model_arn],
        )
    )
    knowledge_base_role.add_to_policy(
        iam.PolicyStatement(
            actions=["s3:GetObject", "s3:ListBucket"],
            resources=[uploads_bucket.bucket_arn, f"{uploads_bucket.bucket_arn}/*"],
        )
    )
    knowledge_base_role.add_to_policy(
        iam.PolicyStatement(
            actions=[
                "s3vectors:PutVectors",
                "s3vectors:GetVectors",
                "s3vectors:DeleteVectors",
                "s3vectors:QueryVectors",
                "s3vectors:GetIndex",
            ],
            resources=[knowledge_base_vector_index.attr_index_arn],
        )
    )

    knowledge_base = bedrock.CfnKnowledgeBase(
        scope,
        "StudyBotKnowledgeBase",
        name=KB_NAME,
        role_arn=knowledge_base_role.role_arn,
        knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
            type="VECTOR",
            vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                embedding_model_arn=embedding_model_arn,
            ),
        ),
        storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
            type="S3_VECTORS",
            s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                vector_bucket_arn=knowledge_base_vector_bucket.attr_vector_bucket_arn,
                index_arn=knowledge_base_vector_index.attr_index_arn,
            ),
        ),
    )
    kb_role_default_policy = knowledge_base_role.node.try_find_child("DefaultPolicy")
    if kb_role_default_policy is not None:
        knowledge_base.node.add_dependency(kb_role_default_policy)

    knowledge_data_source = bedrock.CfnDataSource(
        scope,
        "StudyBotKnowledgeBaseDataSource",
        name=KB_DATA_SOURCE_NAME,
        knowledge_base_id=knowledge_base.ref,
        data_deletion_policy="DELETE",
        data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
            type="S3",
            s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                bucket_arn=uploads_bucket.bucket_arn,
                inclusion_prefixes=["processed/"],
            ),
        ),
        vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
            chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                chunking_strategy="FIXED_SIZE",
                fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                    max_tokens=400,
                    overlap_percentage=20,
                ),
            ),
        ),
    )
    knowledge_data_source.node.add_dependency(knowledge_base)

    knowledge_base_id = knowledge_base.attr_knowledge_base_id
    data_source_id = knowledge_data_source.attr_data_source_id
    kb_arn = knowledge_base.attr_knowledge_base_arn
    data_source_arn = (
        f"arn:{stack.partition}:bedrock:{stack.region}:{stack.account}:"
        f"knowledge-base/{knowledge_base_id}/data-source/{data_source_id}"
    )
    return KnowledgeBaseResources(
        vector_bucket=knowledge_base_vector_bucket,
        vector_index=knowledge_base_vector_index,
        role=knowledge_base_role,
        knowledge_base=knowledge_base,
        data_source=knowledge_data_source,
        kb_arn=kb_arn,
        data_source_arn=data_source_arn,
        vector_index_arn=knowledge_base_vector_index.attr_index_arn,
        knowledge_base_id=knowledge_base_id,
        data_source_id=data_source_id,
    )
