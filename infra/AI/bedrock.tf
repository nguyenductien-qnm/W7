locals {
  studybot_account_id = "589077667575"
  studybot_region     = "ap-southeast-1"
  studybot_tags = {
    Project     = "StudyBot"
    Environment = "W7Demo"
    ManagedBy   = "Terraform"
  }
}

# Current live resource:
#   Knowledge Base ID: LI32IWLOB5
#   ARN: arn:aws:bedrock:ap-southeast-1:589077667575:knowledge-base/LI32IWLOB5
#   Status: ACTIVE
#
# Import command:
#   terraform import aws_bedrockagent_knowledge_base.studybot LI32IWLOB5
resource "aws_bedrockagent_knowledge_base" "studybot" {
  name        = "studybot-kb"
  description = "StudyBot document knowledge base backed by S3 Vectors."
  role_arn    = "arn:aws:iam::589077667575:role/StudyBotBedrockStack-KnowledgeBaseRoleA2B317B9-UycR9VjqexH0"

  knowledge_base_configuration {
    type = "VECTOR"

    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:ap-southeast-1::foundation-model/cohere.embed-english-v3"
    }
  }

  storage_configuration {
    type = "S3_VECTORS"

    s3_vectors_configuration {
      index_arn = "arn:aws:s3vectors:ap-southeast-1:589077667575:bucket/studybot-vectors-589077667575-ap-southeast-1/index/studybot-kb-index"
    }
  }

  tags = local.studybot_tags
}

# Current live resource:
#   Data Source ID: BZ8NQGYFCX
#   Name: studybot-uploads
#   Status: AVAILABLE
#
# Import command:
#   terraform import aws_bedrockagent_data_source.studybot_uploads LI32IWLOB5,BZ8NQGYFCX
resource "aws_bedrockagent_data_source" "studybot_uploads" {
  knowledge_base_id     = aws_bedrockagent_knowledge_base.studybot.id
  name                  = "studybot-uploads"
  data_deletion_policy  = "DELETE"

  data_source_configuration {
    type = "S3"

    s3_configuration {
      bucket_arn              = "arn:aws:s3:::studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk"
      bucket_owner_account_id = local.studybot_account_id
      inclusion_prefixes      = ["documents/"]
    }
  }
}
