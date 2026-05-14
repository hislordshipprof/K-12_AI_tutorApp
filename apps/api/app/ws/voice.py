"""WebSocket endpoint ``/ws/voice/{session_id}``.

The browser opens a WebSocket here; we bridge it to Gemini's Live API
via :class:`app.agents.voice.VoiceBridge`. The Supabase JWT is passed
via the ``?token=`` query param — browsers can't easily set
``Authorization`` headers on a WS upgrade.

Protocol envelope
─────────────────

    client → server
        {"type": "audio",    "audio": "<base64 PCM 16kHz mono>"}
        {"type": "text",     "text":  "..."}
        {"type": "end_turn"}

    server → client
        {"type": "ready"}                                       (on connect)
        {"type": "audio",    "audio": "<base64 PCM 24kHz>"}
        {"type": "transcript", "text": "..."}
        {"type": "turn_complete"}
        {"type": "error",    "message": "..."}
        {"type": "done"}

Auth modes
──────────
- Normal: ``?token=<supabase-jwt>``. Bad / expired → ``close(4401)``.
- Dev (``DEV_MODE=true``): a missing token is accepted as ``dev-user``
  so frontend devs can poke the bridge without a real session token.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, WebSocket

from app.agents.voice import VoiceBridge
from app.core.config import settings
from app.core.logging import get_logger
from app.core.rate_limit import voice_acquire, voice_release
from app.core.security import verify_supabase_jwt
from app.core.session_auth import assert_session_owner_ws
from app.services.gemini import get_gemini

router = APIRouter()
log = get_logger(__name__)


@router.websocket("/ws/voice/{session_id}")
async def voice_ws(
    websocket: WebSocket,
    session_id: str,
    token: str | None = Query(default=None),
    topic: str | None = Query(default=None),
) -> None:
    """Bridge a browser WebSocket to a Gemini Live session.

    The connection is closed with status 4401 when authentication fails
    so that the client JS can distinguish "wrong creds" from a generic
    1006 drop.
    """
    user_id: str | None = None

    # ── auth ─────────────────────────────────────────────────────────────
    if not token:
        if settings.is_dev:
            user_id = "dev-user"
            log.info(
                "voice_ws_dev_accept",
                session_id=session_id,
                note="DEV_MODE=true → accepting connection without token",
            )
        else:
            log.warning("voice_ws_missing_token", session_id=session_id)
            await websocket.close(code=4401, reason="missing token")
            return
    else:
        try:
            claims = verify_supabase_jwt(token)
        except Exception as e:  # noqa: BLE001 — auth failures shouldn't crash the worker
            log.warning(
                "voice_ws_auth_failed",
                session_id=session_id,
                error=str(e),
            )
            await websocket.close(code=4401, reason="invalid token")
            return
        user_id = claims.get("sub")

    # ── ownership check ──────────────────────────────────────────────────
    # Service-role bridges bypass RLS, so confirm the authenticated user
    # actually owns this session before opening the Gemini Live tunnel.
    try:
        sess_uuid = UUID(session_id)
    except (TypeError, ValueError):
        await websocket.close(code=4400, reason="invalid session_id")
        return
    if user_id and not await assert_session_owner_ws(sess_uuid, str(user_id)):
        log.warning(
            "voice_ws_not_session_owner",
            session_id=session_id,
            user_id=user_id,
        )
        await websocket.close(code=4403, reason="session not owned by user")
        return

    # ── concurrency gate (1 voice WS per user) ────────────────────────────
    # Voice bridges Gemini Live — the most expensive surface. Cap to a
    # single concurrent session per authenticated user.
    gate_user = str(user_id or "anon")
    if not await voice_acquire(gate_user):
        log.warning("voice_ws_rate_limited", session_id=session_id, user_id=gate_user)
        await websocket.close(code=4429, reason="too many concurrent voice sessions")
        return

    # ── bridge ───────────────────────────────────────────────────────────
    bridge = VoiceBridge(get_gemini())
    try:
        await bridge.run(
            websocket,
            session_id=session_id,
            user_id=user_id,
            topic_name=topic,
        )
    finally:
        await voice_release(gate_user)
