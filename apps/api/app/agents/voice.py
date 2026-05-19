"""VoiceAgent — Gemini Live API bridge.

A thin coroutine bridge between a browser WebSocket and a Gemini Live
session. The browser streams audio chunks; the server streams audio +
transcripts back.

Protocol envelope (client <-> server, both directions are JSON-encoded
text frames — base64 for binary blobs):

    client -> server
        {"type": "audio",          "audio": "<base64 PCM 16kHz mono>"}
        {"type": "text",           "text":  "..."}        # optional user text
        {"type": "end_turn"}                                # finalize this turn
        {"type": "activity_start"}                          # manual-VAD only
        {"type": "activity_end"}                            # manual-VAD only
        {"type": "interrupt"}                               # barge in without speech

    server -> client
        {"type": "ready"}                                   # accepted, bridge up
        {"type": "audio",          "audio": "<base64 PCM>"} # TTS audio chunk
        {"type": "transcript",     "text":  "..."}          # model text fragment
        {"type": "interrupted"}                             # **flush playback NOW**
        {"type": "generation_complete"}                     # model stopped generating
        {"type": "turn_complete"}                           # model finished speaking
        {"type": "error",          "message": "..."}
        {"type": "done"}

The bridge runs two cooperative tasks — `_client_to_gemini` (browser ->
Gemini) and `_gemini_to_client` (Gemini -> browser) — and tears the
session down cleanly when either side disconnects.

The Gemini Live SDK is still in preview; we prefer the non-deprecated
`send_realtime_input` / `send_client_content` methods and fall back to
`send` if those aren't available on the running SDK.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.logging import get_logger
from app.services.gemini import GeminiService

log = get_logger(__name__)


ARIA_VOICE_SYSTEM = (
    "You are Aria, a friendly high school physics tutor (grades 9-12). "
    "Speak warmly and naturally. Use plain conversational language. "
    "Never just give the answer — ask the student what they think first, "
    "guide them with hints, celebrate small wins. Keep responses short."
)


# ── helpers ──────────────────────────────────────────────────────────────────
async def _send_audio_chunk(session: Any, pcm: bytes) -> None:
    """Forward a PCM chunk to the Live API.

    Prefers `send_realtime_input` (current SDK), falls back to the
    deprecated `send` with the legacy input dict so this code keeps
    working against older preview builds.
    """
    audio_blob = {"data": pcm, "mime_type": "audio/pcm;rate=16000"}
    if hasattr(session, "send_realtime_input"):
        await session.send_realtime_input(audio=audio_blob)
        return
    # Legacy fallback — SDK <2.0 shape.
    await session.send(input=audio_blob)  # type: ignore[call-arg]


async def _send_text(session: Any, text: str, *, turn_complete: bool = True) -> None:
    """Forward a plain text turn to the Live API."""
    if hasattr(session, "send_client_content"):
        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": text}]},
            turn_complete=turn_complete,
        )
        return
    await session.send(input=text, end_of_turn=turn_complete)  # type: ignore[call-arg]


async def _signal_end_of_turn(session: Any) -> None:
    """Tell the Live API the user has finished speaking (auto-VAD mode)."""
    if hasattr(session, "send_realtime_input"):
        # The current SDK takes an explicit activity_end signal OR an
        # `audio_stream_end=True`. Either is acceptable.
        try:
            await session.send_realtime_input(audio_stream_end=True)
            return
        except TypeError:
            # Older preview builds might not know audio_stream_end.
            pass
    if hasattr(session, "send_client_content"):
        await session.send_client_content(turns=None, turn_complete=True)
        return
    await session.send(input=None, end_of_turn=True)  # type: ignore[call-arg]


async def _send_activity_start(session: Any) -> None:
    """Manual-VAD: signal the model that the user just started speaking.

    Only used when the client has disabled automatic VAD (push-to-talk).
    In auto-VAD mode the server detects speech itself and this is unused.
    """
    if hasattr(session, "send_realtime_input"):
        try:
            await session.send_realtime_input(activity_start={})
            return
        except TypeError:
            pass


async def _send_activity_end(session: Any) -> None:
    """Manual-VAD: signal the model that the user just stopped speaking."""
    if hasattr(session, "send_realtime_input"):
        try:
            await session.send_realtime_input(activity_end={})
            return
        except TypeError:
            pass


async def _force_interrupt(session: Any) -> None:
    """Client-initiated barge-in: force the model to yield without speech.

    Used when the user taps a "stop talking" button. We send an empty
    activity_start which the model treats as "user is taking the floor",
    which in turn triggers the `interrupted` signal on the response stream.
    """
    if hasattr(session, "send_realtime_input"):
        try:
            await session.send_realtime_input(activity_start={})
            return
        except TypeError:
            pass


# ── bridge ───────────────────────────────────────────────────────────────────
class VoiceBridge:
    """Bidirectional WebSocket bridge between browser and Gemini Live."""

    def __init__(self, gemini: GeminiService):
        self.gemini = gemini

    async def run(
        self,
        client_ws: WebSocket,
        session_id: str,
        user_id: str | None,
        topic_name: str | None = None,
    ) -> None:
        """Open a Gemini Live session and proxy messages bidirectionally.

        This method handles the full lifecycle — accept + ready ack, the
        Live session context, both pump tasks, and cleanup. It never
        raises; all errors are logged + reported to the client as an
        ``{"type": "error", ...}`` frame when possible.
        """
        await client_ws.accept()
        log.info(
            "voice_session_open",
            session_id=session_id,
            user_id=user_id,
            topic=topic_name,
        )
        await self._send_client(client_ws, {"type": "ready"})

        # Build the system prompt (Aria persona + topic context) and ask
        # the wrapper to wire it into the Live session config along with
        # AUDIO modality — the native-audio model rejects empty configs.
        system_prompt = ARIA_VOICE_SYSTEM + (
            f" The current lesson is on {topic_name}." if topic_name else ""
        )
        log.debug("voice_system_prompt", session_id=session_id, prompt=system_prompt)

        try:
            async with self.gemini.get_live_client(
                system_instruction=system_prompt,
                response_modalities=["AUDIO"],
            ) as gemini_session:
                await self._pump_until_done(
                    client_ws=client_ws,
                    gemini_session=gemini_session,
                    session_id=session_id,
                )
        except WebSocketDisconnect:
            log.info("voice_client_disconnected_early", session_id=session_id)
        except Exception as exc:  # noqa: BLE001 — top-level safety net
            log.exception(
                "voice_bridge_failed",
                session_id=session_id,
                error=str(exc),
            )
            await self._send_client(
                client_ws, {"type": "error", "message": str(exc)}
            )
        finally:
            await self._send_client(client_ws, {"type": "done"})
            try:
                await client_ws.close()
            except Exception:  # noqa: BLE001 — best-effort close
                pass
            log.info("voice_session_closed", session_id=session_id)

    # ---- pump tasks ---------------------------------------------------------
    async def _pump_until_done(
        self,
        *,
        client_ws: WebSocket,
        gemini_session: Any,
        session_id: str,
    ) -> None:
        """Run the two relay coroutines concurrently until either ends."""

        async def client_to_gemini() -> None:
            try:
                while True:
                    raw = await client_ws.receive_text()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        log.warning(
                            "voice_invalid_json",
                            session_id=session_id,
                            raw_preview=raw[:200],
                        )
                        continue

                    t = msg.get("type")
                    if t == "audio":
                        audio_b64 = msg.get("audio") or ""
                        try:
                            pcm = base64.b64decode(audio_b64, validate=True)
                        except (ValueError, base64.binascii.Error) as e:
                            await self._send_client(
                                client_ws,
                                {"type": "error", "message": f"bad audio b64: {e}"},
                            )
                            continue
                        await _send_audio_chunk(gemini_session, pcm)
                    elif t == "text":
                        await _send_text(
                            gemini_session,
                            msg.get("text", ""),
                            turn_complete=True,
                        )
                    elif t == "end_turn":
                        await _signal_end_of_turn(gemini_session)
                    elif t == "activity_start":
                        # Push-to-talk: student just pressed the mic button.
                        await _send_activity_start(gemini_session)
                    elif t == "activity_end":
                        # Push-to-talk: student just released the mic button.
                        await _send_activity_end(gemini_session)
                    elif t == "interrupt":
                        # Student tapped "stop talking" — barge in without
                        # actually speaking. The model will respond with a
                        # `server_content.interrupted=True` frame which we
                        # forward to the client to flush playback.
                        log.info(
                            "voice_client_initiated_interrupt",
                            session_id=session_id,
                        )
                        await _force_interrupt(gemini_session)
                    else:
                        log.debug(
                            "voice_unknown_client_msg",
                            session_id=session_id,
                            type=t,
                        )
            except WebSocketDisconnect:
                log.info("voice_client_disconnected", session_id=session_id)
            except Exception as e:  # noqa: BLE001
                log.exception(
                    "voice_client_pump_error",
                    session_id=session_id,
                    error=str(e),
                )

        async def gemini_to_client() -> None:
            try:
                async for response in gemini_session.receive():
                    audio = getattr(response, "data", None)
                    text = getattr(response, "text", None)
                    if audio:
                        await self._send_client(
                            client_ws,
                            {
                                "type": "audio",
                                "audio": base64.b64encode(audio).decode("ascii"),
                            },
                        )
                    if text:
                        await self._send_client(
                            client_ws, {"type": "transcript", "text": text}
                        )
                    server_content = getattr(response, "server_content", None)
                    if server_content is not None:
                        # Live transcription of the *student's* speech —
                        # enabled via `input_audio_transcription` in the
                        # session config. Gemini surfaces it incrementally
                        # as `input_transcription.text` fragments; relay
                        # each one as a `transcript` frame so the classroom
                        # can track what the student is saying in real time.
                        input_tx = getattr(
                            server_content, "input_transcription", None
                        )
                        tx_text = getattr(input_tx, "text", None)
                        if tx_text:
                            await self._send_client(
                                client_ws,
                                {"type": "transcript", "text": tx_text},
                            )
                        # Gemini Live signals barge-in with `interrupted=True`
                        # on the same payload that delivered the
                        # already-emitted text/audio. The client MUST flush
                        # its playback queue the moment it sees this — see
                        # docs/interruption-architecture.md § Voice.
                        if getattr(server_content, "interrupted", False):
                            log.info(
                                "voice_interrupted",
                                session_id=session_id,
                            )
                            await self._send_client(
                                client_ws, {"type": "interrupted"}
                            )
                        # `generation_complete` (model finished generating)
                        # is distinct from `turn_complete` (the model has
                        # also finished speaking the last queued chunk).
                        # Emitting both lets the UI dim "Aria speaking…"
                        # before the student actually replies.
                        if getattr(server_content, "generation_complete", False):
                            await self._send_client(
                                client_ws, {"type": "generation_complete"}
                            )
                        if getattr(server_content, "turn_complete", False):
                            await self._send_client(
                                client_ws, {"type": "turn_complete"}
                            )
            except WebSocketDisconnect:
                # Client window closed mid-receive.
                log.info(
                    "voice_client_disconnected_during_recv",
                    session_id=session_id,
                )
            except Exception as e:  # noqa: BLE001
                log.exception(
                    "voice_gemini_recv_error",
                    session_id=session_id,
                    error=str(e),
                )
                await self._send_client(
                    client_ws, {"type": "error", "message": str(e)}
                )

        t1 = asyncio.create_task(client_to_gemini(), name="voice_client_to_gemini")
        t2 = asyncio.create_task(gemini_to_client(), name="voice_gemini_to_client")
        done, pending = await asyncio.wait(
            {t1, t2}, return_when=asyncio.FIRST_COMPLETED
        )
        for p in pending:
            p.cancel()
            try:
                await p
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        # Surface the first exception (if any) for the outer handler to log.
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc

    # ---- transport helper ---------------------------------------------------
    @staticmethod
    async def _send_client(ws: WebSocket, payload: dict[str, Any]) -> None:
        """Send a JSON frame; swallow disconnect/runtime errors silently."""
        try:
            await ws.send_text(json.dumps(payload))
        except (WebSocketDisconnect, RuntimeError):
            # Connection already gone — caller will notice on next op.
            pass
        except Exception:  # noqa: BLE001
            # Don't let transport hiccups crash the bridge.
            log.debug("voice_send_failed", payload_type=payload.get("type"))


# Module-level reference so callers can introspect available voices /
# the system prompt without instantiating a bridge.
__all__ = ["ARIA_VOICE_SYSTEM", "VoiceBridge"]


# Settings accessor kept here purely for symmetry with other agents that
# read `settings` lazily; some callers may want to inspect the live model
# name without importing the config module separately.
def get_live_model_name() -> str:
    """Return the currently-configured Gemini Live model identifier."""
    return settings.gemini_model_live
