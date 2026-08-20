terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "frontend_urls" {
  description = "Origins the Cognito app client is allowed to redirect back to."
  type        = list(string)
  default     = ["http://localhost:3000/", "http://localhost:3000/login/callback"]
}

variable "logout_urls" {
  type    = list(string)
  default = ["http://localhost:3000/"]
}

variable "my_ip_cidr" {
  description = "Your current public IP, /32 — the only address allowed to reach RDS and SSH directly. Get it via `curl https://checkip.amazonaws.com`, then pass it with -var or a terraform.tfvars (gitignored) — no default on purpose, this shouldn't be a real IP committed to source control."
  type        = string
}

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ── Cognito: identity provider + login page ────────────────────────────────

resource "aws_cognito_user_pool" "vyom" {
  name = "vyom-users"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 10
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  admin_create_user_config {
    allow_admin_create_user_only = false
  }
}

# Hosted UI domain — must be globally unique across all AWS accounts, so it's
# derived from the account id rather than a name someone else might already hold.
resource "aws_cognito_user_pool_domain" "vyom" {
  domain       = "vyom-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.vyom.id
}

# Public SPA client (Next.js) — no client secret, since a secret embedded in
# frontend JS isn't actually secret. Auth code + PKCE flow via Amplify.
resource "aws_cognito_user_pool_client" "frontend" {
  name         = "vyom-frontend"
  user_pool_id = aws_cognito_user_pool.vyom.id

  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    # Admin-initiated auth (server-side, e.g. `aws cognito-idp admin-initiate-auth`)
    # — used for scripted testing and any future server-side user provisioning.
    # Never exposed to the frontend, which only ever uses SRP via Amplify.
    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
  ]

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = var.frontend_urls
  logout_urls   = var.logout_urls

  access_token_validity  = 60 # minutes
  id_token_validity      = 60
  refresh_token_validity = 30 # days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

# ── Bedrock Guardrail: prompt-injection / off-topic defense ────────────────
# Applied to generation only (BedrockProvider.generate/stream) — embedding
# and reranking always run locally regardless, see providers/local.py.

resource "aws_bedrock_guardrail" "vyom" {
  name        = "vyom-guardrail"
  description = "Prompt-injection defense for Vyom's generation calls."

  blocked_input_messaging   = "This request can't be processed — it looks like an attempt to override Vyom's instructions rather than a genuine question about Indian financial or regulatory data."
  blocked_outputs_messaging = "I can't provide that response — it would go beyond what's grounded in the retrieved BSE/SEBI/RBI context."

  content_policy_config {
    filters_config {
      type = "PROMPT_ATTACK"
      # HIGH blocks even LOW-confidence detections — in practice this meant
      # ordinary financial follow-up questions got blocked once conversation
      # history/context grew large enough (a long, Q&A-transcript-shaped
      # prompt reads as injection-like to the classifier independent of
      # actual content). MEDIUM only blocks MEDIUM/HIGH-confidence hits,
      # which real injection attempts still trigger.
      input_strength  = "MEDIUM"
      output_strength = "NONE" # PROMPT_ATTACK only evaluates input
    }
  }
}

resource "aws_bedrock_guardrail_version" "vyom" {
  guardrail_arn = aws_bedrock_guardrail.vyom.guardrail_arn
  description   = "Phase 1 — prompt-injection defense"
}

# ── RDS: PostgreSQL + pgvector, replaces local Docker Postgres as the ingest
# target — see scripts/ingest_to_rds.py. Manual local→RDS ingestion only,
# no AWS-side pipeline, per the Phase 2 scoping decision.

resource "random_password" "rds" {
  length  = 24
  special = false # avoid characters that need extra escaping in connection strings
}

resource "aws_security_group" "rds" {
  name        = "vyom-rds"
  description = "Vyom RDS Postgres - inbound 5432 from operator IP only" # NOTE: stale text — AWS SG descriptions are immutable, changing it forces replacement
  vpc_id      = data.aws_vpc.default.id

  # Both ingress rules MUST stay inline (not a separate aws_security_group_rule
  # resource) — mixing the two on the same aws_security_group causes Terraform
  # to reconcile the group back to only its inline-declared rules on every
  # apply, silently deleting anything added via a standalone resource. This
  # bit us once already: the EC2 rule vanished on the very next apply after
  # Phase 3, and RDS connectivity from the instance broke without any config
  # change actually intending that.
  ingress {
    description = "Postgres from operator laptop"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.my_ip_cidr]
  }

  ingress {
    description     = "Postgres from the app EC2 instance"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "vyom" {
  identifier     = "vyom-db"
  engine         = "postgres"
  engine_version = "16.10"
  instance_class = "db.t4g.micro" # dev-scale usage, not production traffic

  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = "vyom"
  username = "vyom"
  password = random_password.rds.result

  publicly_accessible    = true
  vpc_security_group_ids = [aws_security_group.rds.id]
  skip_final_snapshot    = true # dev instance — no need to retain a snapshot on destroy

  backup_retention_period = 1
}

# ── ElastiCache: Redis, provisioned alongside RDS per your direction — not
# yet used by anything (ingest never touches Redis; the live API isn't
# deployed to AWS yet, so nothing runs inside this VPC to reach it). VPC-only
# by design, no public-accessibility option — see infra plan notes.

resource "aws_elasticache_subnet_group" "vyom" {
  name       = "vyom-redis"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_security_group" "redis" {
  name        = "vyom-redis"
  description = "Vyom ElastiCache Redis - VPC-internal only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Redis from within the default VPC"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.default.cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_elasticache_cluster" "vyom" {
  cluster_id           = "vyom-redis"
  engine               = "redis"
  node_type            = "cache.t4g.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.vyom.name
  security_group_ids   = [aws_security_group.redis.id]
}

# ── EC2: single instance running both the FastAPI backend (systemd) and the
# static frontend (nginx) — see infra/user_data.sh for the OS-level bootstrap,
# app code + config deployed separately (see infra/README / deploy notes).
# Deliberately not Lambda/App Runner/ECS: embed_query()/rerank() still run
# local PyTorch models in-process on every query (see providers/bedrock.py),
# so an always-on box avoids reloading ~1-2GB of models on every cold start.
# Portfolio project, not production — plain HTTP on AWS's default domain,
# no ALB/ACM/Route53.

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_key_pair" "ec2" {
  key_name   = "vyom-ec2"
  public_key = file(pathexpand("~/.ssh/vyom_ec2.pub"))
}

resource "aws_security_group" "ec2" {
  name        = "vyom-ec2"
  description = "Vyom EC2 app server - HTTP public, SSH from operator IP only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH from operator laptop"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# The EC2-into-RDS rule now lives inline in aws_security_group.rds above
# (see the comment there for why it can't be a separate resource).
# Redis's security group already allows the whole default-VPC CIDR block
# (see aws_security_group.redis above), which already covers this instance —
# no rule needed there.

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "vyom-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# Browser-based Session Manager access as a fallback to SSH — no extra cost.
resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Scoped to exactly what BedrockProvider.generate()/stream()/check_guardrail()
# call — Converse/ConverseStream map to the InvokeModel* IAM actions, not a
# separate "Converse" action. No embedded access keys anywhere: this role is
# how the running app authenticates to Bedrock.
data "aws_iam_policy_document" "ec2_bedrock" {
  statement {
    sid       = "Generate"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["arn:aws:bedrock:${var.aws_region}::foundation-model/mistral.mistral-large-3-675b-instruct"]
  }
  statement {
    sid       = "Guardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.vyom.guardrail_arn]
  }
}

resource "aws_iam_role_policy" "ec2_bedrock" {
  name   = "vyom-bedrock-access"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.ec2_bedrock.json
}

resource "aws_iam_instance_profile" "ec2" {
  name = "vyom-ec2"
  role = aws_iam_role.ec2.name
}

resource "aws_instance" "app" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = "m7i-flex.large"
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2.name
  key_name                    = aws_key_pair.ec2.key_name
  associate_public_ip_address = true

  user_data = file("${path.module}/user_data.sh")

  root_block_device {
    volume_size = 30 # AL2023's AMI snapshot requires >= 30GB
    volume_type = "gp3"
  }

  tags = {
    Name = "vyom-app"
  }
}

resource "aws_eip" "app" {
  instance = aws_instance.app.id
  domain   = "vpc"
}

# ── Phase 4: observability & monitoring ─────────────────────────────────────
# CloudWatch-native (no Grafana — one less service to run on an already
# small box), console-only alarms (no SNS/email) — per your direction.

# CloudWatch Agent on the EC2 instance ships logs + the OS metrics EC2
# doesn't collect by default (mem/disk usage — CPU/network/disk-I/O-count
# already are). Reuses the existing ec2 role rather than a new one.
resource "aws_iam_role_policy_attachment" "ec2_cloudwatch_agent" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_cloudwatch_log_group" "nginx_access" {
  name              = "/vyom/nginx/access"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "nginx_error" {
  name              = "/vyom/nginx/error"
  retention_in_days = 14
}

# Structured per-request JSON events (query.py's _log_completion via
# app.py's dedicated "vyom.events" logger, settings.event_log_path) — a
# separate stream from the app's normal human-readable log (which stays in
# journald, untouched), specifically so CloudWatch's JSON metric filters
# below have pure JSON lines to parse.
resource "aws_cloudwatch_log_group" "vyom_events" {
  name              = "/vyom/events"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_metric_filter" "error_count" {
  name           = "vyom-error-count"
  log_group_name = aws_cloudwatch_log_group.vyom_events.name
  pattern        = "{ $.status = \"error\" }"

  metric_transformation {
    name          = "ErrorCount"
    namespace     = "Vyom/App"
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "blocked_count" {
  name           = "vyom-blocked-count"
  log_group_name = aws_cloudwatch_log_group.vyom_events.name
  pattern        = "{ $.status = \"blocked\" }"

  metric_transformation {
    name          = "BlockedCount"
    namespace     = "Vyom/App"
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "request_latency" {
  name           = "vyom-request-latency"
  log_group_name = aws_cloudwatch_log_group.vyom_events.name
  pattern        = "{ $.event = \"query_complete\" }"

  metric_transformation {
    name      = "RequestLatencyMs"
    namespace = "Vyom/App"
    value     = "$.latency_ms"
  }
}

# ── Health-check Lambda — dependency-free (no torch/heavy deps, nothing
# like the constraint that ruled out Lambda for the main app), no VPC
# (hits the EC2 instance's public endpoint over the internet, not the
# private RDS/ElastiCache path).

data "archive_file" "health_check" {
  type        = "zip"
  source_file = "${path.module}/lambda/health_check.py"
  output_path = "${path.module}/lambda/health_check.zip"
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "health_check" {
  name               = "vyom-health-check"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "health_check_logs" {
  role       = aws_iam_role.health_check.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "health_check_metrics" {
  statement {
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"] # PutMetricData has no resource-level scoping
  }
}

resource "aws_iam_role_policy" "health_check_metrics" {
  name   = "vyom-health-check-metrics"
  role   = aws_iam_role.health_check.id
  policy = data.aws_iam_policy_document.health_check_metrics.json
}

resource "aws_lambda_function" "health_check" {
  function_name    = "vyom-health-check"
  role             = aws_iam_role.health_check.arn
  handler          = "health_check.handler"
  runtime          = "python3.12"
  timeout          = 10
  filename         = data.archive_file.health_check.output_path
  source_code_hash = data.archive_file.health_check.output_base64sha256

  environment {
    variables = {
      HEALTH_URL = "http://${aws_eip.app.public_ip}/health"
    }
  }
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "vyom-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.health_check.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name   = "vyom-scheduler-invoke"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}

resource "aws_scheduler_schedule" "health_check" {
  name       = "vyom-health-check"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = "rate(5 minutes)"

  target {
    arn      = aws_lambda_function.health_check.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}

# ── Alarms — console-visible only (no alarm_actions/SNS, per your direction) ─

resource "aws_cloudwatch_metric_alarm" "ec2_status_check" {
  alarm_name          = "vyom-ec2-status-check-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  dimensions = {
    InstanceId = aws_instance.app.id
  }
}

resource "aws_cloudwatch_metric_alarm" "ec2_cpu_high" {
  alarm_name          = "vyom-ec2-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  dimensions = {
    InstanceId = aws_instance.app.id
  }
}

resource "aws_cloudwatch_metric_alarm" "health_check_down" {
  alarm_name          = "vyom-health-check-down"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Up"
  namespace           = "Vyom/HealthCheck"
  period              = 300
  statistic           = "Minimum"
  threshold           = 1
  treat_missing_data  = "breaching"
}

resource "aws_cloudwatch_metric_alarm" "error_rate_high" {
  alarm_name          = "vyom-error-rate-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.error_count.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.error_count.metric_transformation[0].namespace
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
}

# Dimensions confirmed from the running agent's actual reported metrics
# (device/fstype vary by instance — not safe to guess ahead of time).
resource "aws_cloudwatch_metric_alarm" "ec2_disk_high" {
  alarm_name          = "vyom-ec2-disk-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "disk_used_percent"
  namespace           = "CWAgent"
  period              = 300
  statistic           = "Average"
  threshold           = 85
  dimensions = {
    InstanceId = aws_instance.app.id
    path       = "/"
    device     = "nvme0n1p1"
    fstype     = "xfs"
  }
}

# ── Dashboard ────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "vyom" {
  dashboard_name = "vyom"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 8, height = 6,
        properties = {
          title   = "EC2 CPU %"
          metrics = [["AWS/EC2", "CPUUtilization", "InstanceId", aws_instance.app.id]]
          period  = 300, stat = "Average", region = var.aws_region
        }
      },
      {
        type = "metric", x = 8, y = 0, width = 8, height = 6,
        properties = {
          title   = "EC2 memory %"
          metrics = [["CWAgent", "mem_used_percent", "InstanceId", aws_instance.app.id]]
          period  = 300, stat = "Average", region = var.aws_region
        }
      },
      {
        type = "metric", x = 16, y = 0, width = 8, height = 6,
        properties = {
          title   = "Health check (1 = up)"
          metrics = [["Vyom/HealthCheck", "Up"]]
          period  = 300, stat = "Minimum", region = var.aws_region
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 8, height = 6,
        properties = {
          title   = "Request latency (ms)"
          metrics = [["Vyom/App", "RequestLatencyMs"]]
          period  = 300, stat = "Average", region = var.aws_region
        }
      },
      {
        type = "metric", x = 8, y = 6, width = 8, height = 6,
        properties = {
          title = "Errors / blocked (count)"
          metrics = [
            ["Vyom/App", "ErrorCount", { label = "Errors" }],
            ["Vyom/App", "BlockedCount", { label = "Blocked" }],
          ]
          period = 300, stat = "Sum", region = var.aws_region
        }
      },
    ]
  })
}

# ── Outputs consumed by the app (.env) ──────────────────────────────────────

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.vyom.id
}

output "cognito_app_client_id" {
  value = aws_cognito_user_pool_client.frontend.id
}

output "cognito_hosted_ui_domain" {
  value = "${aws_cognito_user_pool_domain.vyom.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "cognito_issuer_url" {
  value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.vyom.id}"
}

output "bedrock_guardrail_id" {
  value = aws_bedrock_guardrail.vyom.guardrail_id
}

output "bedrock_guardrail_version" {
  value = aws_bedrock_guardrail_version.vyom.version
}

output "rds_endpoint" {
  value = aws_db_instance.vyom.address
}

output "rds_database_url" {
  value     = "postgresql://${aws_db_instance.vyom.username}:${random_password.rds.result}@${aws_db_instance.vyom.address}:5432/${aws_db_instance.vyom.db_name}"
  sensitive = true
}

output "redis_endpoint" {
  value = aws_elasticache_cluster.vyom.cache_nodes[0].address
}

output "ec2_public_ip" {
  value = aws_eip.app.public_ip
}

output "ec2_public_dns" {
  value = aws_instance.app.public_dns
}
