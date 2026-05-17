"""Tests for `POST /v1/tts` — dedicated-TTS read-aloud (task M.2).

`model-strategy.md` §3b: `/v1/tts` is a one-shot `generate_content` call
against a dedicated TTS model — `GeminiService.synthesize_speech` returns
raw PCM, the endpoint wraps it as a WAV blob. `synthesize_speech` is mocked
so no network call is made.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.gemini import GeminiService

# Fake 16-bit mono PCM payload the mocked TTS model "returns".
_PCM = b"\x01\x02" * 1024


def test_tts_returns_a_wav_blob(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful synthesis returns `audio/wav` — a 44-byte RIFF/WAVE
    header followed by the model's PCM."""
    monkeypatch.setattr(
        GeminiService, "synthesize_speech", AsyncMock(return_value=_PCM)
    )
    r = client.post(
        "/v1/tts",
        headers=dev_headers,
        json={"text": "Pressure is force per unit area."},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    body = r.content
    assert body[:4] == b"RIFF"
    assert body[8:12] == b"WAVE"
    assert body.endswith(_PCM)
    assert len(body) == 44 + len(_PCM)  # canonical header + PCM


def test_tts_passes_the_requested_voice_to_the_model(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The request's `voice` is forwarded to `synthesize_speech`."""
    mock = AsyncMock(return_value=_PCM)
    monkeypatch.setattr(GeminiService, "synthesize_speech", mock)
    r = client.post(
        "/v1/tts",
        headers=dev_headers,
        json={"text": "Hello there.", "voice": "Kore"},
    )
    assert r.status_code == 200
    assert mock.await_args.args == ("Hello there.", "Kore")


def test_tts_defaults_the_voice_when_omitted(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no `voice` in the request, the default voice is used."""
    mock = AsyncMock(return_value=_PCM)
    monkeypatch.setattr(GeminiService, "synthesize_speech", mock)
    r = client.post("/v1/tts", headers=dev_headers, json={"text": "Hi."})
    assert r.status_code == 200
    assert mock.await_args.args == ("Hi.", "Aoede")


def test_tts_blank_text_is_400(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whitespace-only text strips to empty and is rejected with 400."""
    monkeypatch.setattr(
        GeminiService, "synthesize_speech", AsyncMock(return_value=_PCM)
    )
    r = client.post("/v1/tts", headers=dev_headers, json={"text": "   "})
    assert r.status_code == 400


def test_tts_upstream_failure_is_502(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure inside `synthesize_speech` surfaces as 502, not 500."""
    monkeypatch.setattr(
        GeminiService,
        "synthesize_speech",
        AsyncMock(side_effect=RuntimeError("model unavailable")),
    )
    r = client.post("/v1/tts", headers=dev_headers, json={"text": "Read me."})
    assert r.status_code == 502


def test_tts_empty_audio_is_502(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model returning no audio is a 502, never an empty 200."""
    monkeypatch.setattr(
        GeminiService, "synthesize_speech", AsyncMock(return_value=b"")
    )
    r = client.post("/v1/tts", headers=dev_headers, json={"text": "Read me."})
    assert r.status_code == 502
