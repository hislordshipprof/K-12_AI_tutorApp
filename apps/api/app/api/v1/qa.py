"""Q&A endpoint — Server-Sent Events stream of Aria's Socratic response.

Wired through the stateful ``TutorAgent`` (Phase 3+):

    Client → POST /v1/sessions/{session_id}/qa
         ←  SSE: data: {"type":"token","content":"…"}
         ←  SSE: data: {"type":"done"}
         ←  SSE: data: {"type":"error","message":"…"}

Behaviour change vs. the earlier stub:
    * ``TutorAgent.handle_question`` loads / persists ``agent_state``.
    * Aria's responses are guided by the session context (topic, history,
      hint level, student signals) — see ``app.agents.prompts``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.tutor import TutorAgent, get_tutor
from app.content import scene_tagger
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.core.session_auth import require_session_owner

router = APIRouter(tags=["qa"])
log = get_logger(__name__)


class QAStreamRequest(BaseModel):
    """Body for the stateful Q&A streaming endpoint."""

    question: str = Field(min_length=1, max_length=4000)
    source: Literal["text", "voice", "sketch"] = "text"
    topic_id: str | None = Field(
        default=None,
        description=(
            "Optional topic_id hint — used only when the agent is "
            "initialising state for a brand-new session."
        ),
    )
    step_index: int | None = Field(
        default=None,
        description=(
            "Lesson step the student is currently viewing. Anchors the "
            "agent's RAG retrieval and prompt to the right moment."
        ),
    )
    slide_text: str | None = Field(
        default=None,
        max_length=8000,
        description=(
            "Text of the slide the student is currently looking at, so "
            "Aria can answer questions about what is on screen."
        ),
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/qa")
@limiter.limit("30/minute")
async def ask_question(
    request: Request,
    session_id: UUID,
    body: QAStreamRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[dict[str, Any], Depends(require_session_owner)],
    tutor: Annotated[TutorAgent, Depends(get_tutor)],
) -> StreamingResponse:
    """Stream Aria's Socratic reply, then persist the turn to session state."""

    user_id = str(user.get("sub") or "")
    # `session` was already ownership-verified by the dependency; its
    # presence here guarantees we're reading/writing our own session.
    _ = session

    async def event_stream() -> AsyncGenerator[bytes, None]:
        log.info(
            "qa_start",
            session_id=str(session_id),
            user_id=user_id,
            source=body.source,
        )
        token_count = 0
        try:
            # Draw alongside the answer: keyword-match the question to one
            # of the 12 typed scenes (same rule table the lesson steps use).
            # Emitted as the first frame so the diagram animates while Aria
            # is still composing her reply. No match → text-only answer.
            scene = scene_tagger.tag(body.question, body.question.strip()[:48])
            if scene is not None:
                yield _sse({"type": "scene", "scene": scene}).encode("utf-8")

            async for token in tutor.handle_question(
                session_id=session_id,
                user_id=user_id,
                question=body.question,
                source=body.source,
                topic_id=body.topic_id,
                step_index=body.step_index,
                slide_text=body.slide_text,
            ):
                # Cost-leak guard: stop pulling Gemini tokens the moment the
                # SSE client disconnects. Breaking out of the loop calls the
                # async generator chain's __aexit__, which closes the
                # underlying HTTP/2 stream to Gemini.
                if await request.is_disconnected():
                    log.info(
                        "qa_client_disconnected",
                        session_id=str(session_id),
                        tokens_yielded=token_count,
                    )
                    return
                yield _sse({"type": "token", "content": token}).encode("utf-8")
                token_count += 1
            yield _sse({"type": "done"}).encode("utf-8")
        except asyncio.CancelledError:
            # Starlette tears the response down (e.g. client navigated away
            # mid-stream). Don't emit an error frame — the client is gone.
            log.info(
                "qa_cancelled",
                session_id=str(session_id),
                tokens_yielded=token_count,
            )
            raise
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
