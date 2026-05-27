# Current live resource:
#   Bucket: studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk
#   Region: ap-southeast-1
#   Encryption: SSE-S3 / AES256
#   Public access: blocked
#   CORS: PUT, GET from all origins, expose ETag
#
# Import commands:
#   terraform import aws_s3_bucket.studybot_uploads studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk
#   terraform import aws_s3_bucket_public_access_block.studybot_uploads studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk
#   terraform import aws_s3_bucket_server_side_encryption_configuration.studybot_uploads studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk
#   terraform import aws_s3_bucket_cors_configuration.studybot_uploads studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk
#   terraform import aws_s3_bucket_lifecycle_configuration.studybot_uploads studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk
resource "aws_s3_bucket" "studybot_uploads" {
  bucket        = "studybotdatastack-uploadbucketd2c1da78-2cpeowy02vjk"
  force_destroy = true

  tags = {
    Project     = "StudyBot"
    Environment = "W7Demo"
    ManagedBy   = "Terraform"
  }
}

resource "aws_s3_bucket_public_access_block" "studybot_uploads" {
  bucket = aws_s3_bucket.studybot_uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "studybot_uploads" {
  bucket = aws_s3_bucket.studybot_uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "studybot_uploads" {
  bucket = aws_s3_bucket.studybot_uploads.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT", "GET"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "studybot_uploads" {
  bucket = aws_s3_bucket.studybot_uploads.id

  rule {
    id     = "ExpireIncompleteMultipartUploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  rule {
    id     = "TransitionOldUploads"
    status = "Enabled"

    filter {
      prefix = "documents/"
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}
