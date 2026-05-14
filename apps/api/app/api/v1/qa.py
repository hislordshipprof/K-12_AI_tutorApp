"""Q&A endpoint — Server-Sent Events stream of Gemini text.

The system prompt establishes "Aria", a Socratic tutor that *guides* the
student rather than answering directly. Later agents can swap this for a
LangGraph multi-step plan; the SSE envelope stays the same.

SSE event protocol:
    data: {"type":"token","content":"…"}\n\n
    data: {"type":"done"}\n\n
    data: {"type":"error","message":"…"}\n\n
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.models.schemas import QARequest
from app.services.gemini import GeminiService, get_gemini

router = APIRouter(tags=["qa"])
log = get_logger(__name__)


ARIA_SYSTEM_PROMPT = (
    "You are Aria, a Socratic high school physics tutor. "
    "Never give the answer directly — guide the student with questions and hints. "
    "Break complex ideas into small steps. Praise effort, not innate ability. "
    "When the student is stuck, offer the *smallest* useful nudge."
)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/qa")
async def ask_question(
    session_id: UUID,
    body: QARequest,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    gemini: Annotated[GeminiService, Depends(get_gemini)],
) -> StreamingResponse:
    """Stream Aria's Socratic response as Server-Sent Events."""

    async def event_stream() -> AsyncGenerator[bytes, None]:
        log.info("qa_start", session_id=str(session_id), source=body.source)
        try:
            async for token in gemini.stream_text(
                prompt=body.question,
                system=ARIA_SYSTEM_PROMPT,
            ):
                yield _sse({"type": "token", "content": token}).encode("utf-8")
            yield _sse({"type": "done"}).encode("utf-8")
        except Exception as e:  # noqa: BLE001 — surface failure to the SSE client
            log.exception("qa_stream_failed", session_id=str(session_id))
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
