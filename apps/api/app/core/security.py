"""Supabase JWT verification + FastAPI auth dependency.

Supabase signs access tokens with HS256 using the project's JWT secret.
We decode + validate them server-side so downstream handlers receive the
authenticated user's claims (`sub` is the user id).

For local development (`DEV_MODE=true` or `LOG_LEVEL=DEBUG`) we also accept
a special `X-Dev-User-Id` header so frontend devs can hit the API without
a full Supabase round-trip.
"""

from __future__ import annotations

from typing import Annotated, Any

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Supabase's default audience claim on access tokens.
_SUPABASE_AUDIENCE = "authenticated"


class AuthError(HTTPException):
    """Raised when a request can't be authenticated."""

    def __init__(self, detail: str = "Invalid or missing authentication") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    """Decode and validate a Supabase access token.

    Raises:
        AuthError: if the token is missing, malformed, expired, or signed
            with an unexpected key.
    """
    secret = settings.supabase_jwt_secret.get_secret_value()
    if not secret:
        # No secret configured — refuse to verify (fail closed).
        log.error("supabase_jwt_secret_missing")
        raise AuthError("Server is not configured for authentication.")

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=_SUPABASE_AUDIENCE,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Token has expired.") from e
    except jwt.InvalidAudienceError as e:
        raise AuthError("Invalid token audience.") from e
    except jwt.InvalidTokenError as e:
        log.warning("jwt_invalid", error=str(e))
        raise AuthError("Invalid authentication token.") from e

    return claims  # type: ignore[no-any-return]


def _parse_bearer(authorization: str | None) -> str | None:
    """Extract the raw token from an `Authorization: Bearer …` header."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user_id: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """FastAPI dependency: returns the decoded JWT claims dict.

    - In dev mode (LOG_LEVEL=DEBUG or DEV_MODE=true), an `X-Dev-User-Id`
      header bypasses JWT verification and synthesizes a minimal claims dict.
    - Otherwise: requires a valid `Authorization: Bearer <jwt>` header.
    """
    if settings.is_dev and x_dev_user_id:
        return {
            "sub": x_dev_user_id,
            "aud": _SUPABASE_AUDIENCE,
            "role": "authenticated",
            "dev": True,
        }

    token = _parse_bearer(authorization)
    if not token:
        raise AuthError("Missing bearer token.")

    return verify_supabase_jwt(token)


async def get_optional_user(
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user_id: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | None:
    """Like `get_current_user` but returns `None` when unauthenticated."""
    try:
        return await get_current_user(authorization, x_dev_user_id)
    except HTTPException:
        return None
