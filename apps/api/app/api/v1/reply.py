"""Reply endpoint — student types an answer/attempt, Aria responds Socratically.

Uses the same SSE envelope as the Q&A route so the frontend can share a
single token-streaming handler.

    Client → POST /v1/sessions/{session_id}/reply
    Body   → {"text": "I think amplitude is the height of the wave"}
         ←   SSE: data: {"type":"token","content":"…"}
         ←   SSE: data: {"type":"done"}
         ←   SSE: data: {"type":"error","message":"…"}
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.tutor import TutorAgent, get_tutor
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.core.session_auth import require_session_owner

router = APIRouter(tags=["qa"])
log = get_logger(__name__)


class ReplyRequest(BaseModel):
    """Body for a free-text student reply / answer attempt."""

    text: str = Field(min_length=1, max_length=4000)
    topic_id: str | None = Field(
        default=None,
        description="Optional topic hint when bootstrapping fresh session state.",
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/reply")
@limiter.limit("30/minute")
async def submit_reply(
    request: Request,
    session_id: UUID,
    body: ReplyRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[dict[str, Any], Depends(require_session_owner)],
    tutor: Annotated[TutorAgent, Depends(get_tutor)],
) -> StreamingResponse:
    """Stream Aria's response to a typed student attempt."""

    user_id = str(user.get("sub") or "")
    _ = session  # ownership-verified by dependency

    async def event_stream() -> AsyncGenerator[bytes, None]:
        log.info("reply_start", session_id=str(session_id), user_id=user_id)
        try:
            async for token in tutor.handle_reply(
                session_id=session_id,
                user_id=user_id,
                text=body.text,
                topic_id=body.topic_id,
            ):
                yield _sse({"type": "token", "content": token}).encode("utf-8")
            yield _sse({"type": "done"}).encode("utf-8")
        except Exception as e:  # noqa: BLE001
            log.exception("reply_stream_failed", session_id=str(session_id))
            yield _sse({"type": "error", "message": str(e)}).encode("utf-8")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
