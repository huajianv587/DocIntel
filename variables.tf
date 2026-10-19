variable "aws_region" {
  type    = string
  default = "ap-southeast-1"
}

variable "project_name" {
  type    = string
  default = "docintel"
}

variable "environment" {
  type    = string
  default = "staging"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "api_image" {
  type = string
}

variable "worker_image" {
  type = string
}

variable "frontend_image" {
  type = string
}

variable "db_username" {
  type      = string
  default   = "docintel"
  sensitive = true
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "deepseek_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "github_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "qdrant_cloud_url" {
  type = string
}

variable "qdrant_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "jwt_secret" {
  type      = string
  sensitive = true
}

