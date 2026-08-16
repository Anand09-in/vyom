"""Cognito JWT verification — the auth layer for every route except /health.

Validates the Cognito-issued **ID token** (not the access token — the ID
token carries `email` directly and is the simpler fit for a project with no
separate `users` table, since Cognito itself is the source of truth for
identity here). Verifies against the user pool's JWKS (JSON Web Key Set),
cached in-process and only re-fetched if a token's key id isn't found in
the cache (e.g. after Cognito rotates its signing keys) — not fetched on
every request.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from jose.exceptions import JOSEError

from vyom.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user_id: str    # Cognito `sub` — stable, unique per user, used to scope
                     # Redis history keys and query_log rows
    email: str | None


@lru_cache
def _jwks(issuer_url: str) -> dict:
    resp = httpx.get(f"{issuer_url}/.well-known/jwks.json", timeout=5.0)
    resp.raise_for_status()
    return resp.json()


def _find_key(jwks: dict, kid: str) -> dict | None:
    return next((k for k in jwks["keys"] if k["kid"] == kid), None)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    token = creds.credentials
    try:
        header = jwt.get_unverified_header(token)
        jwks = _jwks(settings.cognito_issuer_url)
        key = _find_key(jwks, header["kid"])
        if key is None:
            # Possible key rotation — refresh the cache once before failing.
            _jwks.cache_clear()
            jwks = _jwks(settings.cognito_issuer_url)
            key = _find_key(jwks, header["kid"])
        if key is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown signing key")

        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.cognito_app_client_id,
            issuer=settings.cognito_issuer_url,
        )
    except JOSEError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc

    if claims.get("token_use") != "id":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Expected a Cognito ID token")

    return CurrentUser(user_id=claims["sub"], email=claims.get("email"))
