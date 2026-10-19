output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "ecr_repositories" {
  value = {
    api      = aws_ecr_repository.api.repository_url
    worker   = aws_ecr_repository.worker.repository_url
    frontend = aws_ecr_repository.frontend.repository_url
  }
}

output "s3_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "rds_endpoint" {
  value     = aws_db_instance.postgres.address
  sensitive = true
}
