from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from constructs import Construct


class StudyBotInfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        uploads_bucket_name = "studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk"
        documents_table_name = "StudyBotDocuments"
        vector_index_arn = (
            "arn:aws:s3vectors:ap-southeast-1:589077667575:bucket/"
            "studybot-vectors-589077667575-ap-southeast-1/index/studybot-kb-index"
        )
        knowledge_base_id = "LI32IWLOB5"
        data_source_id = "BZ8NQGYFCX"

        uploads_bucket = s3.Bucket.from_bucket_name(
            self,
            "StudyBotUploads",
            bucket_name=uploads_bucket_name,
        )

        documents_table = dynamodb.Table(
            self,
            "StudyBotDocuments",
            table_name=documents_table_name,
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
        )

        CfnOutput(self, "UploadsBucketName", value=uploads_bucket.bucket_name)
        CfnOutput(self, "DocumentsTableName", value=documents_table.table_name)
        CfnOutput(self, "VectorIndexArn", value=vector_index_arn)
        CfnOutput(self, "KnowledgeBaseId", value=knowledge_base_id)
        CfnOutput(self, "DataSourceId", value=data_source_id)
