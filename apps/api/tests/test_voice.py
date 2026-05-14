"""Tests for the Gemini Live voice WebSocket bridge.

These tests fully mock out the Gemini Live SDK — no network is touched.
We swap ``app.services.gemini.get_gemini`` to return a stub that yields
a fake ``AsyncSession`` from its ``get_live_client()`` async context
manager. The fake session records the audio chunks it receives and
emits scripted ``LiveServerMessage``-shaped responses.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.agents.voice import ARIA_VOICE_SYSTEM, VoiceBridge
from app.core.config import settings


# ── stub session plumbing ────────────────────────────────────────────────────
class _FakeLiveSession:
    """Stub Gemini Live AsyncSession.

    Records every call into ``self.sent`` and lets the test drive the
    server-side responses by feeding ``LiveServerMessage``-shaped
    SimpleNamespaces into ``self.outbox``. ``outbox=None`` (default) blocks
    forever — useful when the test only cares about client → server traffic.
    """

    def __init__(self, outbox: list[Any] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self._outbox: asyncio.Queue[Any] = asyncio.Queue()
        if outbox:
            for item in outbox:
                self._outbox.put_nowait(item)
        self._sentinel = object()

    # SDK send variants — only the ones the bridge currently uses.
    async def send_realtime_input(
        self,
        *,
        audio: Any = None,
        audio_stream_end: bool | None = None,
    ) -> None:
        self.sent.append(
            {"op": "send_realtime_input", "audio": audio, "audio_stream_end": audio_stream_end}
        )

    async def send_client_content(
        self,
        *,
        turns: Any = None,
        turn_complete: bool = True,
    ) -> None:
        self.sent.append(
            {"op": "send_client_content", "turns": turns, "turn_complete": turn_complete}
        )

    # iteration support — yield queued items until the sentinel, then end.
    async def receive(self) -> AsyncIterator[Any]:
        while True:
            item = await self._outbox.get()
            if item is self._sentinel:
                return
            yield item

    def end_stream(self) -> None:
        """Cause receive() to terminate normally — drains the outbox loop."""
        self._outbox.put_nowait(self._sentinel)

    def push(self, item: Any) -> None:
        self._outbox.put_nowait(item)


def _make_server_msg(
    *,
    data: bytes | None = None,
    text: str | None = None,
    turn_complete: bool = False,
) -> SimpleNamespace:
    """Shape-compatible stand-in for `LiveServerMessage`.

    The bridge reads ``response.data`` / ``response.text`` (which on the
    real SDK are computed properties) and ``response.server_content.turn_complete``.
    """
    return SimpleNamespace(
        data=data,
        text=text,
        server_content=SimpleNamespace(turn_complete=turn_complete),
    )


class _FakeGemini:
    """Stand-in for `GeminiService` returning a single FakeLiveSession."""

    def __init__(self, session: _FakeLiveSession) -> None:
        self.session = session

    def get_live_client(
        self,
        model: str | None = None,
        system_instruction: str | None = None,
        response_modalities: list[str] | None = None,
        voice_name: str | None = None,
        config: dict | None = None,
    ) -> Any:
        # Capture so tests can assert the bridge plumbed config through.
        self.last_call_kwargs = {
            "model": model,
            "system_instruction": system_instruction,
            "response_modalities": response_modalities,
            "voice_name": voice_name,
            "config": config,
        }
        session = self.session

        @contextlib.asynccontextmanager
        async def _cm() -> AsyncIterator[_FakeLiveSession]:
            try:
                yield session
            finally:
                # Make sure receive() will terminate if it's still running.
                with contextlib.suppress(Exception):
                    session.end_stream()

        return _cm()


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture
def fake_session() -> _FakeLiveSession:
    return _FakeLiveSession()


@pytest.fixture
def install_fake_gemini(
    monkeypatch: pytest.MonkeyPatch,
    fake_session: _FakeLiveSession,
) -> _FakeLiveSession:
    """Make `get_gemini` (as imported by the WS route) return our stub."""
    fake = _FakeGemini(fake_session)
    # The route imports `get_gemini` into its own module namespace, so we
    # patch it there as well as on the services module for completeness.
    monkeypatch.setattr("app.services.gemini.get_gemini", lambda: fake)
    monkeypatch.setattr("app.ws.voice.get_gemini", lambda: fake)
    return fake_session


@pytest.fixture
def app_client() -> Any:
    """Fresh TestClient mounting only the voice router.

    We deliberately do NOT use ``app.main:app`` here — the broader app
    imports modules (e.g. ``app.api.v1.qa``) that may have unrelated
    issues outside this agent's ownership. The voice bridge only needs
    the WebSocket router to be reachable.
    """
    from fastapi import FastAPI

    from app.ws.voice import router as voice_router

    app = FastAPI()
    app.include_router(voice_router)
    with TestClient(app) as c:
        yield c


# ── connection-level tests ───────────────────────────────────────────────────
def test_connect_dev_mode_no_token_accepts(
    app_client: TestClient,
    install_fake_gemini: _FakeLiveSession,
) -> None:
    """In DEV_MODE the route accepts a connection with no token and emits {'type':'ready'}."""
    with app_client.websocket_connect("/ws/voice/test-session") as ws:
        first = json.loads(ws.receive_text())
        assert first == {"type": "ready"}


def test_connect_invalid_token_closes_4401(
    app_client: TestClient,
    install_fake_gemini: _FakeLiveSession,
) -> None:
    """An invalid JWT must close the socket with policy code 4401."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with app_client.websocket_connect(
            "/ws/voice/test-session?token=not-a-real-jwt"
        ) as ws:
            ws.receive_text()  # should never arrive
    assert excinfo.value.code == 4401


def test_connect_valid_jwt_accepts(
    app_client: TestClient,
    install_fake_gemini: _FakeLiveSession,
) -> None:
    """A correctly-signed Supabase JWT is accepted and a ready frame is emitted."""
    secret = settings.supabase_jwt_secret.get_secret_value()
    token = jwt.encode(
        {
            "sub": "user-123",
            "aud": "authenticated",
            "exp": 9_999_999_999,  # year 2286-ish
        },
        secret,
        algorithm="HS256",
    )
    with app_client.websocket_connect(
        f"/ws/voice/test-session?token={token}"
    ) as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "ready"


# ── proxy semantics ──────────────────────────────────────────────────────────
def test_client_audio_forwarded_to_gemini(
    app_client: TestClient,
    install_fake_gemini: _FakeLiveSession,
) -> None:
    """A {'type':'audio'} frame from the browser should land in send_realtime_input."""
    session = install_fake_gemini  # the fake session itself
    pcm = b"\x00\x01\x02\x03" * 8  # 32 bytes of fake PCM
    payload = {"type": "audio", "audio": base64.b64encode(pcm).decode()}

    with app_client.websocket_connect("/ws/voice/test-session") as ws:
        assert json.loads(ws.receive_text()) == {"type": "ready"}
        ws.send_text(json.dumps(payload))
        # Drain the bridge — close ends the connection cleanly.
        # Give the server loop a moment to process the inbound frame.
        for _ in range(20):
            if any(s["op"] == "send_realtime_input" for s in session.sent):
                break
            # Yield briefly via a no-op receive with a tiny timeout would be
            # ideal, but TestClient doesn't expose that — instead trigger a
            # round-trip by sending an end_turn which we know the route handles.
            ws.send_text(json.dumps({"type": "end_turn"}))

    forwarded = [s for s in session.sent if s["op"] == "send_realtime_input" and s["audio"]]
    assert forwarded, f"no audio reached Gemini; sent={session.sent}"
    sent_blob = forwarded[0]["audio"]
    assert sent_blob["data"] == pcm
    assert sent_blob["mime_type"] == "audio/pcm;rate=16000"


def test_gemini_audio_forwarded_to_client(
    app_client: TestClient,
    install_fake_gemini: _FakeLiveSession,
) -> None:
    """Audio bytes emitted by the fake Live session must reach the client as base64."""
    session = install_fake_gemini
    gemini_audio = b"\xde\xad\xbe\xef" * 4
    session.push(_make_server_msg(data=gemini_audio))
    session.push(_make_server_msg(text="Hello, student!"))
    session.push(_make_server_msg(turn_complete=True))
    session.end_stream()  # tells the bridge's receive loop to finish

    with app_client.websocket_connect("/ws/voice/test-session") as ws:
        msgs: list[dict[str, Any]] = []
        # Pull frames until 'done' arrives (sent by the finally-block).
        while True:
            try:
                msgs.append(json.loads(ws.receive_text()))
            except WebSocketDisconnect:
                break
            if msgs[-1].get("type") == "done":
                break

    # The bridge sends, in order: ready, audio, transcript, turn_complete, done.
    types_in_order = [m["type"] for m in msgs]
    assert types_in_order[0] == "ready"
    assert "audio" in types_in_order
    assert "transcript" in types_in_order
    assert "turn_complete" in types_in_order
    assert types_in_order[-1] == "done"

    audio_frame = next(m for m in msgs if m["type"] == "audio")
    assert base64.b64decode(audio_frame["audio"]) == gemini_audio

    transcript_frame = next(m for m in msgs if m["type"] == "transcript")
    assert transcript_frame["text"] == "Hello, student!"


def test_client_text_routes_to_send_client_content(
    app_client: TestClient,
    install_fake_gemini: _FakeLiveSession,
) -> None:
    """A {'type':'text'} from the client should call send_client_content."""
    session = install_fake_gemini
    with app_client.websocket_connect("/ws/voice/test-session") as ws:
        assert json.loads(ws.receive_text()) == {"type": "ready"}
        ws.send_text(json.dumps({"type": "text", "text": "Hi Aria!"}))
        # Trigger one more pass to let the loop run.
        for _ in range(20):
            if any(s["op"] == "send_client_content" for s in session.sent):
                break
            ws.send_text(json.dumps({"type": "end_turn"}))

    text_calls = [s for s in session.sent if s["op"] == "send_client_content"]
    assert text_calls, f"send_client_content was never called; sent={session.sent}"
    first = text_calls[0]
    assert first["turns"]["role"] == "user"
    assert first["turns"]["parts"][0]["text"] == "Hi Aria!"
    assert first["turn_complete"] is True


def test_bad_audio_b64_emits_error_frame(
    app_client: TestClient,
    install_fake_gemini: _FakeLiveSession,
) -> None:
    """A malformed base64 audio payload should produce an {'type':'error'} reply,
    without tearing the socket down (the bridge keeps relaying).
    """
    with app_client.websocket_connect("/ws/voice/test-session") as ws:
        assert json.loads(ws.receive_text()) == {"type": "ready"}
        ws.send_text(json.dumps({"type": "audio", "audio": "!!!not-base64!!!"}))
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "error"
        assert "b64" in msg["message"].lower() or "base64" in msg["message"].lower()


# ── unit checks on the agent module ──────────────────────────────────────────
def test_aria_voice_system_prompt_mentions_tutor() -> None:
    """Cheap smoke check on the agent's persona prompt — the brand name
    'Aria' and the word 'physics' should both be present so the system
    prompt isn't accidentally truncated by future refactors.
    """
    assert "Aria" in ARIA_VOICE_SYSTEM
    assert "physics" in ARIA_VOICE_SYSTEM


def test_bridge_is_constructible_with_gemini_stub(fake_session: _FakeLiveSession) -> None:
    """VoiceBridge should accept any object exposing get_live_client — duck typing only."""
    bridge = VoiceBridge(_FakeGemini(fake_session))
    # Attribute access only — we don't run it here.
    assert callable(bridge.gemini.get_live_client)
