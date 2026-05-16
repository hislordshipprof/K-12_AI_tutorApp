"""Supabase JWT verification + FastAPI auth dependency.

Supabase signs access tokens with either HS256 (the legacy shared secret)
or, by default on newer projects, an asymmetric algorithm (ES256/RS256)
whose public keys are published at the project's JWKS endpoint. We verify
both, picking the strategy from each token's own `alg` header, so
downstream handlers receive the authenticated user's claims (`sub` is the
user id).

For local development (`DEV_MODE=true` or `LOG_LEVEL=DEBUG`) we also accept
a special `X-Dev-User-Id` header so frontend devs can hit the API without
a full Supabase round-trip.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger
from app.core.supabase import get_supabase

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


# Lazily-built JWKS client — verifies Supabase's asymmetric (ES256/RS256)
# access tokens. Modern Supabase projects sign with rotating ECC keys
# published at the project's JWKS endpoint; PyJWKClient fetches + caches
# them by `kid`.
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    """Lazily build (and cache) the JWKS client for this Supabase project."""
    global _jwks_client
    if _jwks_client is None:
        base = settings.supabase_url.rstrip("/")
        _jwks_client = jwt.PyJWKClient(f"{base}/auth/v1/.well-known/jwks.json")
    return _jwks_client


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    """Decode and validate a Supabase access token.

    The verification key depends on the token's own `alg` header:
    * ``HS256`` — the legacy shared secret (`SUPABASE_JWT_SECRET`); also the
      path the test suite exercises.
    * ``ES256`` / ``RS256`` — the modern Supabase default; the public key is
      fetched from the project's JWKS endpoint, selected by `kid`.

    Raises:
        AuthError: if the token is missing, malformed, expired, or signed
            with an unexpected / untrusted key.
    """
    try:
        alg = str(jwt.get_unverified_header(token).get("alg", ""))
    except jwt.InvalidTokenError as e:
        log.warning("jwt_malformed_header", error=str(e))
        raise AuthError("Invalid authentication token.") from e

    key: Any
    if alg == "HS256":
        secret = settings.supabase_jwt_secret.get_secret_value()
        if not secret:
            # No secret configured — refuse to verify (fail closed).
            log.error("supabase_jwt_secret_missing")
            raise AuthError("Server is not configured for authentication.")
        key = secret
    elif alg in ("ES256", "RS256"):
        if not settings.supabase_url:
            log.error("supabase_url_missing")
            raise AuthError("Server is not configured for authentication.")
        try:
            key = _get_jwks_client().get_signing_key_from_jwt(token).key
        except Exception as e:  # noqa: BLE001 — PyJWK lookup / network failure
            log.warning("jwks_key_fetch_failed", error=str(e))
            raise AuthError("Invalid authentication token.") from e
    else:
        log.warning("jwt_unsupported_alg", alg=alg)
        raise AuthError("Invalid authentication token.")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[alg],
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


def get_user_role(user_id: str) -> str:
    """Look up a user's `profiles.role`, defaulting to `'student'`.

    Returns `'student'` whenever Supabase is unreachable or the row is
    missing — the conservative default for a role check (least privilege).
    """
    supabase = get_supabase()
    if supabase is None:
        return "student"
    try:
        resp = (
            supabase.table("profiles")
            .select("role")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if rows:
            return str(rows[0].get("role") or "student")
    except Exception as e:  # noqa: BLE001
        log.warning("get_user_role_lookup_failed", error=str(e))
    return "student"


def require_role(
    *allowed: str,
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]:
    """FastAPI dependency factory: 403s unless the caller's role is allowed.

    Usage:

        @router.post(..., dependencies=[Depends(require_role("admin"))])

    or, to also receive the claims:

        user = Depends(require_role("admin"))
    """

    async def _checker(
        user: Annotated[dict[str, Any], Depends(get_current_user)],
    ) -> dict[str, Any]:
        sub = str(user.get("sub") or "")
        role = get_user_role(sub)
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(allowed)}.",
            )
        return user

    return _checker
