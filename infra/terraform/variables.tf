variable "aws_region" {
  description = "AWS region for the StudyCloud environment."
  type        = string
  default     = "ap-southeast-2"
}

variable "aws_profile" {
  description = "Named AWS CLI profile used by Terraform."
  type        = string
  default     = "project"
}

variable "project_name" {
  type    = string
  default = "studycloud"
}

variable "environment" {
  type    = string
  default = "semester"
}

variable "api_lambda_package_path" {
  description = "Path to the backend Lambda ZIP after its AWS storage adapter and Mangum entry point are ready."
  type        = string
  default     = "../../backend/dist/api.zip"
}

variable "worker_lambda_package_path" {
  description = "Path to the multi-format document worker Lambda ZIP."
  type        = string
  default     = "../../worker/dist/worker.zip"
}

variable "api_lambda_timeout_seconds" {
  type    = number
  default = 60
}

variable "worker_lambda_memory_mb" {
  type    = number
  default = 2048
}
