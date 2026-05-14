"""Reaction endpoint — student taps an emoji, Aria replies + updates signals.

Reactions are short, canned responses (no LLM call) plus a side-effect on
``SessionState.student_signals``. The frontend pops these up as toast-style
messages and uses ``applied: true`` to acknowledge the state mutation.

    Client → POST /v1/sessions/{session_id}/reaction
    Body   → {"reaction": "slower" | "confused" | "got_it" | "mind_blown"}
         ←   200 OK  → {"message": "...", "applied": true}
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agents.tutor import TutorAgent, get_tutor
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.session_auth import require_session_owner

router = APIRouter(tags=["qa"])
log = get_logger(__name__)


ReactionType = Literal["slower", "confused", "got_it", "mind_blown"]


class ReactionRequest(BaseModel):
    """Body for the reaction endpoint."""

    reaction: ReactionType
    topic_id: str | None = None


class ReactionResponse(BaseModel):
    message: str
    applied: bool


@router.post("/sessions/{session_id}/reaction", response_model=ReactionResponse)
async def submit_reaction(
    session_id: UUID,
    body: ReactionRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[dict[str, Any], Depends(require_session_owner)],
    tutor: Annotated[TutorAgent, Depends(get_tutor)],
) -> ReactionResponse:
    """Record the student's emoji reaction and return Aria's canned reply."""
    user_id = str(user.get("sub") or "")
    _ = session  # ownership-verified by dependency
    log.info(
        "reaction_received",
        session_id=str(session_id),
        user_id=user_id,
        reaction=body.reaction,
    )
    message = await tutor.handle_reaction(
        session_id=session_id,
        user_id=user_id,
        reaction=body.reaction,
        topic_id=body.topic_id,
    )
    return ReactionResponse(message=message, applied=True)
