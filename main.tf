data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name = "${var.project_name}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "public" {
  for_each                = { for index, az in local.azs : az => index }
  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.key
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, each.value)
  map_public_ip_on_launch = true
}

resource "aws_subnet" "private" {
  for_each          = { for index, az in local.azs : az => index }
  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, each.value + 10)
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "alb" {
  name   = "${local.name}-alb"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service" {
  name   = "${local.name}-service"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "data" {
  name   = "${local.name}-data"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }
}

resource "aws_db_subnet_group" "postgres" {
  name       = "${local.name}-postgres"
  subnet_ids = [for subnet in aws_subnet.private : subnet.id]
}

resource "aws_db_instance" "postgres" {
  identifier              = local.name
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = "db.t4g.micro"
  allocated_storage       = 20
  max_allocated_storage   = 100
  db_name                 = "docintel"
  username                = var.db_username
  password                = var.db_password
  db_subnet_group_name    = aws_db_subnet_group.postgres.name
  vpc_security_group_ids  = [aws_security_group.data.id]
  publicly_accessible     = false
  skip_final_snapshot     = true
  deletion_protection     = false
  backup_retention_period = 7
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${local.name}-redis"
  subnet_ids = [for subnet in aws_subnet.private : subnet.id]
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = replace(local.name, "_", "-")
  description                = "DocIntel Celery and cache Redis"
  engine                     = "redis"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = 1
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.data.id]
  automatic_failover_enabled = false
  transit_encryption_enabled = true
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${local.name}-artifacts-"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_secretsmanager_secret" "runtime" {
  name                    = "${local.name}/runtime"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "runtime" {
  secret_id = aws_secretsmanager_secret.runtime.id
  secret_string = jsonencode({
    DEEPSEEK_API_KEY = var.deepseek_api_key
    GITHUB_TOKEN     = var.github_token
    QDRANT_API_KEY   = var.qdrant_api_key
    JWT_SECRET       = var.jwt_secret
    DATABASE_URL     = "postgresql+psycopg://${urlencode(var.db_username)}:${urlencode(var.db_password)}@${aws_db_instance.postgres.address}:5432/docintel"
    REDIS_URL        = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
  })
}

resource "aws_ecr_repository" "api" {
  name                 = "${local.name}/api"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "worker" {
  name                 = "${local.name}/worker"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${local.name}/frontend"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 30
}

resource "aws_iam_role" "ecs_execution" {
  name = "${local.name}-ecs-execution"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  role = aws_iam_role.ecs_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.runtime.arn]
    }]
  })
}

resource "aws_iam_role" "ecs_task" {
  name = "${local.name}-ecs-task"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "ecs_task" {
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"], Resource = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"] },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.runtime.arn] }
    ]
  })
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_lb" "main" {
  name               = substr(local.name, 0, 32)
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [for subnet in aws_subnet.public : subnet.id]
}

resource "aws_lb_target_group" "api" {
  name        = substr("${local.name}-api", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check { path = "/health" }
}

resource "aws_lb_target_group" "frontend" {
  name        = substr("${local.name}-web", 0, 32)
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check { path = "/" }
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener" "frontend" {
  load_balancer_arn = aws_lb.main.arn
  port              = 8080
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

locals {
  common_env = [
    { name = "ENVIRONMENT", value = var.environment },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "S3_BUCKET", value = aws_s3_bucket.artifacts.bucket },
    { name = "S3_ENDPOINT_URL", value = "" },
    { name = "QDRANT_URL", value = var.qdrant_cloud_url },
  ]
  common_secrets = [
    { name = "DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.runtime.arn}:DATABASE_URL::" },
    { name = "REDIS_URL", valueFrom = "${aws_secretsmanager_secret.runtime.arn}:REDIS_URL::" },
    { name = "DEEPSEEK_API_KEY", valueFrom = "${aws_secretsmanager_secret.runtime.arn}:DEEPSEEK_API_KEY::" },
    { name = "GITHUB_TOKEN", valueFrom = "${aws_secretsmanager_secret.runtime.arn}:GITHUB_TOKEN::" },
    { name = "QDRANT_API_KEY", valueFrom = "${aws_secretsmanager_secret.runtime.arn}:QDRANT_API_KEY::" },
    { name = "JWT_SECRET", valueFrom = "${aws_secretsmanager_secret.runtime.arn}:JWT_SECRET::" }
  ]
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  container_definitions = jsonencode([{
    name             = "api", image = var.api_image, essential = true, portMappings = [{ containerPort = 8000 }], environment = local.common_env, secrets = local.common_secrets,
    command          = ["/bin/sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"],
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "api" } }
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  container_definitions = jsonencode([{
    name             = "worker", image = var.worker_image, essential = true, environment = local.common_env, secrets = local.common_secrets,
    command          = ["celery", "-A", "app.celery_app.celery_app", "worker", "--loglevel=INFO", "--concurrency=2"],
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "worker" } }
  }])
}

resource "aws_ecs_task_definition" "sandbox" {
  family                   = "${local.name}-sandbox"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn
  container_definitions = jsonencode([{
    name             = "sandbox", image = "public.ecr.aws/docker/library/python:3.12-slim", essential = true,
    command          = ["python", "-c", "print('sandbox task must be supplied code by the worker')"],
    environment      = [{ name = "PYTHONDONTWRITEBYTECODE", value = "1" }],
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "sandbox" } }
  }])
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name             = "frontend", image = var.frontend_image, essential = true, portMappings = [{ containerPort = 8080 }],
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "frontend" } }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = [for subnet in aws_subnet.public : subnet.id]
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.api]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = [for subnet in aws_subnet.public : subnet.id]
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }
}

resource "aws_ecs_service" "frontend" {
  name            = "frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = [for subnet in aws_subnet.public : subnet.id]
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 8080
  }
  depends_on = [aws_lb_listener.frontend]
}
