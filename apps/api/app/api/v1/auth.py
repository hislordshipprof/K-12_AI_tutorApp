"""Auth-adjacent onboarding endpoints.

`POST /v1/auth/redeem-teacher-invite` lets a signed-in user redeem a
teacher invite code issued by an admin. On success the caller's
`profiles.role` is set to `'teacher'` and the invite is marked redeemed
so it cannot be reused (teacher-authoring.md §10, §11.1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


class RedeemInviteRequest(BaseModel):
    """Body for `POST /v1/auth/redeem-teacher-invite`."""

    code: str = Field(min_length=1, max_length=64)


@router.post("/redeem-teacher-invite")
async def redeem_teacher_invite(
    body: RedeemInviteRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Redeem a teacher invite code → promote the caller to `role='teacher'`.

    Errors:
      - 404 if the code does not exist.
      - 409 if the code has already been redeemed (it cannot be reused).
    """
    code = body.code.strip()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An invite code is required.",
        )

    user_id = str(user.get("sub") or "")

    supabase = get_supabase()
    if supabase is None:
        # No Supabase (local dev placeholder) — there is no invite store to
        # validate against, so the redeem flow cannot run honestly here.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="invite redemption unavailable",
        )

    # 1. Look up the invite.
    try:
        resp = (
            supabase.table("teacher_invites")
            .select("code,redeemed_by,redeemed_at")
            .eq("code", code)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("redeem_invite_lookup_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="invite redemption unavailable",
        ) from e

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That invite code is not valid.",
        )

    invite = rows[0]
    if invite.get("redeemed_by"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That invite code has already been used.",
        )

    now = datetime.now(timezone.utc).isoformat()

    # 2. Mark the invite redeemed — scoped to `redeemed_by is null` so a race
    #    between two redeemers can only let one through (the other's update
    #    matches zero rows).
    try:
        claim = (
            supabase.table("teacher_invites")
            .update({"redeemed_by": user_id, "redeemed_at": now})
            .eq("code", code)
            .is_("redeemed_by", "null")
            .execute()
        )
        claimed = getattr(claim, "data", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("redeem_invite_claim_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="invite redemption unavailable",
        ) from e

    if not claimed:
        # Someone else redeemed it between our read and write.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That invite code has already been used.",
        )

    # 3. Promote the caller to teacher.
    try:
        (
            supabase.table("profiles")
            .update({"role": "teacher"})
            .eq("id", user_id)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        log.warning("redeem_invite_promote_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="invite redemption unavailable",
        ) from e

    return {"role": "teacher", "code": code}
