"""Provider factory — the single place that picks local vs. bedrock.

Everything else in the codebase depends only on the Provider interface,
so switching VYOM_PROVIDER in .env is the only change needed to redeploy.
"""
from __future__ import annotations

from vyom.config import Settings, get_settings
from vyom.providers.base import Provider

__all__ = ["Provider", "get_provider"]


def get_provider(settings: Settings | None = None) -> Provider:
    """Build the Provider for the configured backend.

    Heavy vendor imports live inside each branch so importing this module
    never pulls in torch or boto3 unless that provider is actually selected.
    """
    settings = settings or get_settings()

    if settings.provider == "local":
        from vyom.providers.local import LocalProvider

        return LocalProvider(settings)
    elif settings.provider == "bedrock":
        from vyom.providers.bedrock import BedrockProvider

        return BedrockProvider(settings)
    else:
        raise ValueError(f"Unknown provider: {settings.provider!r}")
