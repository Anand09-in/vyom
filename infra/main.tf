terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
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

data "aws_caller_identity" "current" {}

# ── Cognito: identity provider + login page ────────────────────────────────

resource "aws_cognito_user_pool" "vyom" {
  name = "vyom-users"

  username_attributes     = ["email"]
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

  access_token_validity  = 60   # minutes
  id_token_validity      = 60
  refresh_token_validity = 30   # days

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

  blocked_input_messaging = "This request can't be processed — it looks like an attempt to override Vyom's instructions rather than a genuine question about Indian financial or regulatory data."
  blocked_outputs_messaging = "I can't provide that response — it would go beyond what's grounded in the retrieved BSE/SEBI/RBI context."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE" # PROMPT_ATTACK only evaluates input
    }
  }
}

resource "aws_bedrock_guardrail_version" "vyom" {
  guardrail_arn = aws_bedrock_guardrail.vyom.guardrail_arn
  description   = "Phase 1 — prompt-injection defense"
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
