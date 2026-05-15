"""``POST /v1/tts`` — natural-voice TTS via Gemini Live.

The browser's built-in `speechSynthesis` API is robotic on platforms
without neural voices installed. This endpoint produces a real WAV
clip with Aria's voice using the Gemini Live native-audio model.

Trade-off vs. streaming: we collect the full PCM stream then return one
WAV blob, so the client gets ~1-2s setup latency before audio starts.
For lesson-step playback (5-15s utterances) that's acceptable and
dramatically simpler than wiring PCM chunks through an AudioWorklet.

Response shape: ``audio/wav`` binary, 24 kHz mono 16-bit. The client
plays it via the standard ``<audio>`` element or ``Audio`` API.
"""

from __future__ import annotations

import asyncio
import io
import struct
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.agents.prompts import ARIA_BASE_PERSONA
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.services.gemini import GeminiService, get_gemini

log = get_logger(__name__)
router = APIRouter(tags=["tts"])


SAMPLE_RATE = 24_000  # Gemini Live native-audio output rate.
MAX_TEXT_LEN = 800  # Lesson steps are ≤120 chars; cap at 800 for safety.
DEFAULT_VOICE = "Aoede"  # Warm, female. Other options: Charon, Kore, Fenrir, Puck.


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LEN)
    voice: str | None = None


def _wrap_pcm_as_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Prepend a minimal RIFF/WAVE header to raw 16-bit mono PCM.

    Gemini Live emits raw PCM. Browsers can't decode raw PCM directly,
    so we wrap with the canonical 44-byte WAV header.
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


async def _send_text_turn(session: Any, text: str) -> None:
    """Send a single user text turn and signal end-of-turn.

    Mirrors `agents.voice._send_text` but kept inline so this module
    doesn't drag in the full WebSocket bridge surface.
    """
    if hasattr(session, "send_client_content"):
        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": text}]},
            turn_complete=True,
        )
        return
    # SDK <2.0 fallback.
    await session.send(input=text, end_of_turn=True)  # type: ignore[call-arg]


async def _collect_pcm(session: Any, *, idle_timeout_s: float = 8.0) -> bytes:
    """Drain the Live response stream, concatenating all audio bytes.

    Stops when:
      • a `turn_complete` signal arrives on the response, OR
      • no chunk has arrived for `idle_timeout_s` (safety net).
    """
    buf = io.BytesIO()

    async def _read_one() -> bool:
        """Return True when the turn ends and we should stop."""
        async for response in session.receive():
            # The python SDK exposes audio in `data` (raw bytes) on responses
            # whose `server_content.model_turn` contains audio parts.
            data = getattr(response, "data", None)
            if data:
                buf.write(data)
                continue
            # Some SDK versions surface audio inside model_turn parts.
            sc = getattr(response, "server_content", None)
            if sc is not None:
                model_turn = getattr(sc, "model_turn", None)
                if model_turn is not None:
                    for part in getattr(model_turn, "parts", []) or []:
                        inline = getattr(part, "inline_data", None)
                        if inline and getattr(inline, "data", None):
                            buf.write(inline.data)
                # turn_complete / generation_complete are the stop signals.
                if getattr(sc, "turn_complete", False) or getattr(
                    sc, "generation_complete", False
                ):
                    return True
            # Older SDK shape — top-level fields.
            if getattr(response, "turn_complete", False):
                return True
        return False

    try:
        await asyncio.wait_for(_read_one(), timeout=idle_timeout_s + 30)
    except asyncio.TimeoutError as e:
        raise RuntimeError("tts: timed out waiting for Live audio") from e

    return buf.getvalue()


@router.post("/tts")
@limiter.limit("60/minute")
async def synthesize(
    request: Request,  # noqa: ARG001 — slowapi requires the Request param
    body: TTSRequest,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    gemini: Annotated[GeminiService, Depends(get_gemini)],
) -> Response:
    """Synthesize ``body.text`` to a WAV blob via Gemini Live.

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
    # Keep the system instruction VERY short — long persona prose triggers
    # the model to "explain" the request instead of just reading the text.
    system_instruction = (
        f"{ARIA_BASE_PERSONA}\n\n"
        "Read the user's text aloud verbatim, in a warm conversational "
        "tone — like a patient older sibling explaining a concept. Do NOT "
        "add greetings, prefaces, or commentary. Just read the text."
    )

    log.info("tts_start", chars=len(text), voice=voice)

    try:
        async with gemini.get_live_client(
            system_instruction=system_instruction,
            response_modalities=["AUDIO"],
            voice_name=voice,
        ) as session:
            await _send_text_turn(session, text)
            pcm = await _collect_pcm(session)
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
