resource "aws_s3_bucket" "documents" {
  bucket        = "${local.name_prefix}-documents-${random_id.suffix.hex}"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  cors_rule {
    allowed_headers = ["content-type", "x-amz-*", "authorization"]
    allowed_methods = ["PUT", "POST", "GET", "HEAD"]
    allowed_origins = [aws_apigatewayv2_api.http.api_endpoint]
    expose_headers  = ["ETag"]
    max_age_seconds = 300
  }
}

