"""Chalkboard-sketch analysis — multipart upload → SSE analysis stream.

Client posts an image (PNG/JPEG) plus an optional `question` text field.
We base64-encode the image, call Gemini vision, then stream the analysis
text token-by-token to the browser via SSE.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.services.gemini import GeminiService, get_gemini

router = APIRouter(tags=["sketch"])
log = get_logger(__name__)


SKETCH_SYSTEM_PROMPT = (
    "You are Aria, a Socratic tutor reviewing a student's hand-drawn sketch. "
    "Identify what shape, diagram, or equation the student drew. "
    "If their work suggests a misconception, ask a *single* question that "
    "nudges them toward the next step — never give the full answer."
)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/sketch")
async def analyze_sketch(
    session_id: UUID,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    gemini: Annotated[GeminiService, Depends(get_gemini)],
    image: UploadFile = File(...),
    question: str = Form(""),
) -> StreamingResponse:
    """Analyze a student's sketch + question, streaming Aria's response."""
    raw = await image.read()
    img_b64 = base64.b64encode(raw).decode("ascii")
    mime = image.content_type or "image/png"

    user_prompt = (
        SKETCH_SYSTEM_PROMPT
        + "\n\nStudent question: "
        + (question.strip() or "(no question — react to the sketch itself)")
    )

    async def event_stream() -> AsyncGenerator[bytes, None]:
        log.info("sketch_start", session_id=str(session_id), mime=mime)
        try:
            result = await gemini.analyze_image(
                image_b64=img_b64, prompt=user_prompt, mime_type=mime
            )
            text = result.get("text") or ""
            # Naive chunking so the frontend's SSE handler still sees tokens.
            chunk_size = 60
            for i in range(0, len(text), chunk_size):
                yield _sse(
                    {"type": "token", "content": text[i : i + chunk_size]}
                ).encode("utf-8")
            yield _sse({"type": "done", "json": result.get("json")}).encode("utf-8")
        except Exception as e:  # noqa: BLE001
            log.exception("sketch_failed", session_id=str(session_id))
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
