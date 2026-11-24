resource "aws_iam_role" "api" {
  name = "${local.name_prefix}-api"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role" "worker" {
  name = "${local.name_prefix}-worker"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_secretsmanager_secret" "runtime" {
  name                    = "${local.name_prefix}-runtime"
  description             = "StudyCloud JWT signing secret and optional Gemini API key."
  recovery_window_in_days = 0
}

resource "aws_iam_role_policy_attachment" "api_logs" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "worker_logs_vpc" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "api_access" {
  name = "${local.name_prefix}-api-data-access"
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:TransactWriteItems", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem"]
        Resource = aws_dynamodb_table.app.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.documents.arn}/uploads/*", "${aws_s3_bucket.documents.arn}/extracted/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.runtime.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "worker_access" {
  name = "${local.name_prefix}-worker-data-access"
  role = aws_iam_role.worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:PutItem"]
        Resource = aws_dynamodb_table.app.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.documents.arn}/uploads/*", "${aws_s3_bucket.documents.arn}/extracted/*"]
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name_prefix}-api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${local.name_prefix}-worker"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name    = "${local.name_prefix}-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  handler          = "backend.deployment.handler"
  filename         = var.api_lambda_package_path
  source_code_hash = filebase64sha256(var.api_lambda_package_path)
  timeout          = var.api_lambda_timeout_seconds
  memory_size      = 1024

  environment {
    variables = local.common_environment
  }

  depends_on = [aws_cloudwatch_log_group.api]
}

resource "aws_lambda_function" "worker" {
  function_name    = "${local.name_prefix}-worker"
  role             = aws_iam_role.worker.arn
  runtime          = "python3.12"
  handler          = "worker.handler.handler"
  filename         = var.worker_lambda_package_path
  source_code_hash = filebase64sha256(var.worker_lambda_package_path)
  timeout          = 900
  memory_size      = var.worker_lambda_memory_mb

  vpc_config {
    subnet_ids         = aws_subnet.worker_private[*].id
    security_group_ids = [aws_security_group.worker.id]
  }

  environment {
    variables = local.common_environment
  }

  depends_on = [aws_cloudwatch_log_group.worker]
}

resource "aws_lambda_permission" "s3_worker" {
  statement_id   = "AllowS3InvokeWorker"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.worker.arn
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.documents.arn
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_s3_bucket_notification" "documents" {
  bucket = aws_s3_bucket.documents.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.worker.arn
    events              = ["s3:ObjectCreated:Put", "s3:ObjectCreated:Post", "s3:ObjectCreated:CompleteMultipartUpload"]
    filter_prefix       = "uploads/"
  }

  depends_on = [aws_lambda_permission.s3_worker]
}
