"""WebSocket bridge between the browser and Gemini Live (real-time voice).

──────────────────────────────────────────────────────────────────────────────
PROTOCOL ENVELOPE (browser <-> this server)
──────────────────────────────────────────────────────────────────────────────
Client → Server (JSON over text frames, or binary for raw audio):

    { "type": "start",  "session_id": "<uuid>", "voice": "Aria" }
    { "type": "audio",  "data": "<base64 PCM16/16kHz>" }     # or binary frame
    { "type": "text",   "content": "Hello Aria" }
    { "type": "end" }

Server → Client:

    { "type": "ready" }
    { "type": "audio", "data": "<base64 PCM16/24kHz>" }       # TTS audio chunks
    { "type": "text",  "content": "transcription / answer fragment" }
    { "type": "error", "message": "…" }
    { "type": "closed" }

This stub accepts the connection, replies with a single notice, and closes
cleanly — wiring to `GeminiService.get_live_client()` will land in the
voice agent phase.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


@router.websocket("/ws/voice")
async def voice_ws(websocket: WebSocket) -> None:
    """Echo a 'not yet wired' notice, then close gracefully."""
    await websocket.accept()
    log.info("ws_voice_connected", client=str(websocket.client))
    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "message": "voice mode not yet wired — coming in the live-voice phase",
                }
            )
        )
        await websocket.send_text(json.dumps({"type": "closed"}))
    except WebSocketDisconnect:
        log.info("ws_voice_disconnect_during_send")
        return
    finally:
        try:
            await websocket.close(code=1000)
        except RuntimeError:
            # Already closed by client.
            pass
