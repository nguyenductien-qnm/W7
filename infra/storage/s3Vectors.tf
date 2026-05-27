# Current live resources:
#   Vector bucket: studybot-vectors-589077667575-ap-southeast-1
#   Vector index: studybot-kb-index
#   Index ARN: arn:aws:s3vectors:ap-southeast-1:589077667575:bucket/studybot-vectors-589077667575-ap-southeast-1/index/studybot-kb-index
#   Data type: float32
#   Dimensions: 1024
#   Distance metric: cosine
#
# Import commands:
#   terraform import aws_s3vectors_vector_bucket.studybot arn:aws:s3vectors:ap-southeast-1:589077667575:bucket/studybot-vectors-589077667575-ap-southeast-1
#   terraform import aws_s3vectors_index.studybot_kb arn:aws:s3vectors:ap-southeast-1:589077667575:bucket/studybot-vectors-589077667575-ap-southeast-1/index/studybot-kb-index
resource "aws_s3vectors_vector_bucket" "studybot" {
  vector_bucket_name = "studybot-vectors-589077667575-ap-southeast-1"

  tags = {
    Project     = "StudyBot"
    Environment = "W7Demo"
    ManagedBy   = "Terraform"
  }
}

resource "aws_s3vectors_index" "studybot_kb" {
  vector_bucket_name = aws_s3vectors_vector_bucket.studybot.vector_bucket_name
  index_name         = "studybot-kb-index"
  data_type          = "float32"
  dimension          = 1024
  distance_metric    = "cosine"

  tags = {
    Project     = "StudyBot"
    Environment = "W7Demo"
    ManagedBy   = "Terraform"
  }
}
