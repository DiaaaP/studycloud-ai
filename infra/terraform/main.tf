data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_environment = {
    STUDYCLOUD_TABLE_NAME       = aws_dynamodb_table.app.name
    STUDYCLOUD_DOCUMENTS_BUCKET = aws_s3_bucket.documents.id
    STUDYCLOUD_SECRET_ARN       = aws_secretsmanager_secret.runtime.arn
    STUDYCLOUD_STORAGE_BACKEND  = "aws"
  }
}
