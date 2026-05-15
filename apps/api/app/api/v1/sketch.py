"""``POST /v1/sessions/{session_id}/sketch`` — analyze a student's sketch.

Accepts a ``multipart/form-data`` request with:

* ``image`` — PNG or JPEG file (≤ 8 MB)
* ``question`` — optional question text the student typed alongside the sketch
* ``current_step_idx`` — optional integer (lesson step the student is on)

Streams back a Server-Sent-Events response. Each event is a JSON object:

    {"type": "recognition", "shape": ..., "confidence": ..., "intent": ...}
    {"type": "chunk", "delta": "..."}     # Aria's Socratic message tokens
    {"type": "done"}
    {"type": "error", "message": "..."}   # on failure

A best-effort row is also written to the ``sketches`` table after the stream
finishes — via a background task so the student never waits on Supabase.
"""

from __future__ import annotations

import json
import importlib
import importlib.util
import os
import sys
from collections.abc import AsyncGenerator
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.core.session_auth import require_session_owner
from app.services.gemini import GeminiService, get_gemini

log = get_logger(__name__)
router = APIRouter(tags=["sketch"])


# ── Constants ────────────────────────────────────────────────────────────────
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


# ── VisionAgent loader ───────────────────────────────────────────────────────
# The ``app.agents`` package is in flux while sibling agents (socratic / tutor)
# are being built — its ``__init__`` references modules that may not exist yet.
# To stay decoupled from that package's load state, we load ``vision.py`` by
# file path. This keeps the sketch endpoint runnable regardless of whether
# A1's agents are merged.
def _load_vision_module() -> Any:
    """Return the ``app.agents.vision`` module, dodging a broken pkg ``__init__``."""
    # Fast path — already imported (e.g. by tests).
    cached = sys.modules.get("app.agents.vision")
    if cached is not None:
        return cached

    try:
        return importlib.import_module("app.agents.vision")
    except Exception:  # noqa: BLE001 — fall back to direct file load.
        here = os.path.dirname(os.path.abspath(__file__))
        # apps/api/app/api/v1/sketch.py → apps/api/app/agents/vision.py
        vision_path = os.path.abspath(
            os.path.join(here, "..", "..", "agents", "vision.py")
        )
        spec = importlib.util.spec_from_file_location(
            "app.agents.vision", vision_path
        )
        if spec is None or spec.loader is None:  # pragma: no cover — defensive
            raise RuntimeError(
                f"Could not load vision agent module at {vision_path}"
            )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["app.agents.vision"] = mod
        spec.loader.exec_module(mod)
        return mod


# ── Helpers ──────────────────────────────────────────────────────────────────
def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _sniff_mime(raw: bytes, declared: str | None) -> str | None:
    """Return canonical mime type from magic bytes; ``None`` if unknown."""
    if raw.startswith(_PNG_MAGIC):
        return "image/png"
    if raw.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    # Fall back to whatever the client declared, only if it's an image/*.
    if declared and declared.startswith("image/"):
        return declared
    return None


async def _persist_sketch_row(
    session_id: UUID,
    user_id: str | None,
    *,
    png_size: int,
    recognized_shape: str | None,
    ai_response: str,
    question: str | None,
) -> None:
    """Best-effort insert into the ``sketches`` table.

    Failures are logged but never re-raised — saving the sketch is a
    side-effect, not a request-blocking concern.
    """
    try:
        from app.services.supabase import get_supabase_admin  # noqa: WPS433

        client = get_supabase_admin()
        row: dict[str, Any] = {
            "session_id": str(session_id),
            # ``svg_data`` is required by the table; we don't have SVG here, so
            # we record a descriptor noting the image size. A future iteration
            # can upload to storage and store the URL instead.
            "svg_data": f"png:{png_size}B",
            "recognized_shape": recognized_shape,
            "ai_response": ai_response[:4000] if ai_response else None,
        }
        if user_id:
            row["user_id"] = user_id
        if question:
            row["question"] = question[:2000]
        client.table("sketches").insert(row).execute()
        log.info(
            "sketch_saved",
            session_id=str(session_id),
            recognized=recognized_shape,
        )
    except Exception:  # noqa: BLE001 — best-effort persistence
        log.exception("sketch_save_failed", session_id=str(session_id))


# ── Endpoint ─────────────────────────────────────────────────────────────────
@router.post("/sessions/{session_id}/sketch")
@limiter.limit("10/minute")
async def analyze_sketch(
    request: Request,
    session_id: UUID,
    background_tasks: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[dict[str, Any], Depends(require_session_owner)],
    gemini: Annotated[GeminiService, Depends(get_gemini)],
    image: UploadFile = File(...),
    question: str | None = Form(default=None),
    current_step_idx: int | None = Form(default=None),
) -> StreamingResponse:
    """Analyze a student's chalkboard sketch and stream Aria's Socratic reply."""
    _ = session  # ownership-verified by dependency

    # ── 1. Quick size guard from the multipart header ─────────────────────
    if image.size and image.size > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image too large (max 8MB)",
        )

    declared = image.content_type
    if declared and not declared.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image must be image/png or image/jpeg",
        )

    # ── 2. Read body and re-check the size limit ──────────────────────────
    png_bytes = await image.read()
    if len(png_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image too large (max 8MB)",
        )
    if not png_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image body is empty",
        )

    # ── 3. Validate it's actually an image via magic bytes ────────────────
    mime = _sniff_mime(png_bytes, declared)
    if mime is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image must be PNG or JPEG",
        )

    # ── 4. Build the agent ────────────────────────────────────────────────
    vision_mod = _load_vision_module()
    agent = vision_mod.VisionAgent(gemini)

    # ── 4a. Pull lesson + RAG context so Aria anchors her hint in the
    # actual source the student saw — not generic physics knowledge.
    topic_name: str | None = None
    retrieved: list[Any] = []
    topic_id_raw = session.get("topic_id") if isinstance(session, dict) else None
    if topic_id_raw:
        try:
            from app.content import retriever as rag_retriever
            from app.core.supabase import get_supabase

            sb = get_supabase()
            if sb is not None:
                t_resp = (
                    sb.table("topics")
                    .select("name")
                    .eq("id", str(topic_id_raw))
                    .limit(1)
                    .execute()
                )
                t_rows = getattr(t_resp, "data", None) or []
                if t_rows:
                    topic_name = t_rows[0].get("name")

            # Use the student's question if they typed one; otherwise probe
            # by topic name so retrieval still surfaces the relevant chunk.
            rag_query = (question or topic_name or "").strip()
            if rag_query:
                retrieved = await rag_retriever.fetch_context(
                    topic_id=str(topic_id_raw),
                    question=rag_query,
                    last_step_idx=current_step_idx,
                    supabase=None,  # let the retriever build its own
                )
        except Exception as e:  # noqa: BLE001 — never block the sketch on RAG failure
            log.warning("sketch_rag_fetch_failed", error=str(e))
            retrieved = []

    # We collect a small summary while streaming so the background task can
    # save a meaningful row.
    summary: dict[str, Any] = {"shape": None, "text_parts": []}

    async def event_stream() -> AsyncGenerator[bytes, None]:
        log.info(
            "sketch_stream_start",
            session_id=str(session_id),
            user=user.get("sub"),
            mime=mime,
            bytes=len(png_bytes),
            current_step_idx=current_step_idx,
            topic_name=topic_name,
            rag_chunks=len(retrieved),
        )
        try:
            async for ev in agent.analyze_sketch(
                png_bytes=png_bytes,
                topic_name=topic_name,
                question=question,
                mime_type=mime,
                retrieved_chunks=retrieved,
            ):
                if ev.get("type") == "recognition":
                    summary["shape"] = ev.get("shape")
                elif ev.get("type") == "chunk":
                    summary["text_parts"].append(ev.get("delta", ""))
                yield _sse(ev)
        except Exception as e:  # noqa: BLE001 — surface to the SSE client
            log.exception("sketch_stream_failed", session_id=str(session_id))
            yield _sse({"type": "error", "message": str(e)})
            yield _sse({"type": "done"})
        finally:
            # Schedule persistence after the stream completes.
            ai_response = " ".join(summary["text_parts"]).strip()
            background_tasks.add_task(
                _persist_sketch_row,
                session_id,
                user.get("sub"),
                png_size=len(png_bytes),
                recognized_shape=summary["shape"],
                ai_response=ai_response,
                question=question,
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
