"""``POST /v1/tts`` — natural-voice read-aloud via a dedicated TTS model.

The browser's built-in `speechSynthesis` API is robotic on platforms
without neural voices installed. This endpoint produces a real WAV clip
with Aria's voice.

`model-strategy.md` §3b: this used to drive the Gemini **Live**
audio-to-audio model — a conversational model with a deliberately stunted
system prompt, because long persona prose made it *explain* the text
instead of *reading* it. It is now a one-shot `generate_content` call
against a dedicated TTS model (`gemini-3.1-flash-tts-preview`), which reads
**verbatim** by design: no "explain" hack, no per-step Live-session
overhead, lower latency and cost.

Response shape: ``audio/wav`` binary, 24 kHz mono 16-bit. The client plays
it via the standard ``<audio>`` element or ``Audio`` API.
"""

from __future__ import annotations

import struct
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.services.gemini import GeminiService, get_gemini

log = get_logger(__name__)
router = APIRouter(tags=["tts"])


SAMPLE_RATE = 24_000  # Gemini TTS output rate.
MAX_TEXT_LEN = 800  # Lesson steps are ≤120 chars; cap at 800 for safety.
DEFAULT_VOICE = "Aoede"  # Warm, female. Other options: Charon, Kore, Fenrir, Puck.


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LEN)
    voice: str | None = None


def _wrap_pcm_as_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Prepend a minimal RIFF/WAVE header to raw 16-bit mono PCM.

    Gemini TTS emits raw PCM. Browsers can't decode raw PCM directly, so we
    wrap with the canonical 44-byte WAV header.
    """
    bits_per_sample = 16
    channels = 1
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm)
    riff_size = 36 + data_size

    header = b"RIFF"
    header += struct.pack("<I", riff_size)
    header += b"WAVE"
    header += b"fmt "
    header += struct.pack("<I", 16)  # fmt chunk size
    header += struct.pack("<H", 1)  # PCM
    header += struct.pack("<H", channels)
    header += struct.pack("<I", sample_rate)
    header += struct.pack("<I", byte_rate)
    header += struct.pack("<H", block_align)
    header += struct.pack("<H", bits_per_sample)
    header += b"data"
    header += struct.pack("<I", data_size)
    return header + pcm


@router.post("/tts")
@limiter.limit("60/minute")
async def synthesize(
    request: Request,  # noqa: ARG001 — slowapi requires the Request param
    body: TTSRequest,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    gemini: Annotated[GeminiService, Depends(get_gemini)],
) -> Response:
    """Synthesize ``body.text`` to a WAV blob via the dedicated TTS model.

    Returns ``audio/wav`` binary; the client can pipe it straight into an
    `<audio>` element or `new Audio(URL.createObjectURL(blob))`.
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="text is required",
        )

    voice = body.voice or DEFAULT_VOICE
    log.info("tts_start", chars=len(text), voice=voice)

    try:
        pcm = await gemini.synthesize_speech(text, voice)
    except Exception as e:  # noqa: BLE001 — surface as 502 to the client
        log.exception("tts_gemini_failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TTS upstream failed",
        ) from e

    if not pcm:
        log.warning("tts_empty_response", chars=len(text))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TTS produced no audio",
        )

    wav = _wrap_pcm_as_wav(pcm)
    log.info("tts_ok", chars=len(text), pcm_bytes=len(pcm), wav_bytes=len(wav))
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            # `Content-Length` is set automatically by Starlette.
        },
    )
