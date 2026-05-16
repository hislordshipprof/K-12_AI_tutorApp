"""Admin-only endpoints — teacher invite issuance.

`POST /v1/admin/teacher-invites` lets an `admin`-role user mint a fresh
teacher invite code. The code is later redeemed by a signed-in user via
`POST /v1/auth/redeem-teacher-invite`, which sets their `profiles.role`
to `'teacher'` (see `auth.py`).
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import require_role
from app.core.supabase import get_supabase, supabase_enabled

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger(__name__)

# Code alphabet — uppercase + digits, no ambiguous 0/O/1/I/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_code() -> str:
    """A short, human-typable invite code, e.g. `TEACH-7K2QXM`."""
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"TEACH-{body}"


@router.post("/teacher-invites", status_code=status.HTTP_201_CREATED)
async def create_teacher_invite(
    user: Annotated[dict[str, Any], Depends(require_role("admin"))],
) -> dict[str, Any]:
    """Issue a new teacher invite code. Admin-only (a non-admin gets 403)."""
    code = _generate_code()
    admin_id = str(user.get("sub") or "")

    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = (
                supabase.table("teacher_invites")
                .insert({"code": code, "created_by": admin_id})
                .execute()
            )
            rows = getattr(resp, "data", None) or []
            if rows:
                return rows[0]
            raise RuntimeError("insert returned no rows")
        except Exception as e:  # noqa: BLE001
            log.warning("teacher_invite_create_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="invite issuance unavailable",
                ) from e

    # Dev fallback (no Supabase) — return the generated code so the flow is
    # still demonstrable locally.
    return {"code": code, "created_by": admin_id, "redeemed_by": None}
