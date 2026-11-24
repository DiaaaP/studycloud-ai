output "website_url" {
  description = "HTTPS API Gateway URL serving the StudyCloud frontend and /api routes from Lambda."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "api_gateway_url" {
  description = "API Gateway HTTPS endpoint; also serves the frontend and static assets."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "documents_bucket" {
  value = aws_s3_bucket.documents.id
}

output "dynamodb_table" {
  value = aws_dynamodb_table.app.name
}

output "runtime_secret_arn" {
  description = "ARN for the JWT signing secret and optional Gemini API key."
  value       = aws_secretsmanager_secret.runtime.arn
}
