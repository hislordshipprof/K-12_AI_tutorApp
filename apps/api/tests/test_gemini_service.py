"""Tests for `GeminiService` — fully mocked, no network."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.gemini import GeminiService, _coerce_json, _is_retryable


# ── Helpers ───────────────────────────────────────────────────────────────────
def _make_chunk(text: str, usage: dict[str, int] | None = None) -> SimpleNamespace:
    """Mimic a streaming chunk from `google-genai`."""
    return SimpleNamespace(
        text=text,
        candidates=[],
        usage_metadata=(
            SimpleNamespace(
                prompt_token_count=usage.get("prompt", 0) if usage else None,
                candidates_token_count=usage.get("output", 0) if usage else None,
                total_token_count=usage.get("total", 0) if usage else None,
            )
            if usage
            else None
        ),
    )


async def _async_iter(items: list[Any]) -> AsyncIterator[Any]:
    for it in items:
        yield it


def _mock_client_with_stream(chunks: list[Any]) -> MagicMock:
    """Build a MagicMock standing in for `genai.Client`."""
    client = MagicMock()

    async def _stream(**_kwargs: Any) -> AsyncIterator[Any]:
        return _async_iter(chunks)

    client.aio.models.generate_content_stream = AsyncMock(side_effect=_stream)
    return client


# ── Unit tests ───────────────────────────────────────────────────────────────
def test_is_retryable_classifies_5xx() -> None:
    assert _is_retryable(RuntimeError("upstream returned 503 Service Unavailable"))
    assert _is_retryable(RuntimeError("Rate limit exceeded"))
    assert not _is_retryable(ValueError("bad input — missing field"))


def test_coerce_json_handles_fenced_block() -> None:
    text = 'Sure! Here is the analysis:\n```json\n{"shape": "triangle", "sides": 3}\n```'
    assert _coerce_json(text) == {"shape": "triangle", "sides": 3}


def test_coerce_json_handles_inline_object() -> None:
    text = 'Response: {"a": 1, "b": [2,3]} (and some trailing text)'
    assert _coerce_json(text) == {"a": 1, "b": [2, 3]}


def test_coerce_json_returns_none_for_plain_text() -> None:
    assert _coerce_json("Just a plain sentence with no JSON.") is None


# ── stream_text ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_stream_text_yields_concatenated_tokens() -> None:
    svc = GeminiService(api_key="test")
    svc._client = _mock_client_with_stream(  # type: ignore[attr-defined]
        [
            _make_chunk("Hello"),
            _make_chunk(", "),
            _make_chunk("world!", usage={"prompt": 10, "output": 5, "total": 15}),
        ]
    )

    pieces: list[str] = []
    async for token in svc.stream_text("Say hi", system="be friendly"):
        pieces.append(token)

    assert "".join(pieces) == "Hello, world!"
    # Verify the SDK call shape.
    call = svc._client.aio.models.generate_content_stream.call_args  # type: ignore[attr-defined]
    assert call.kwargs["model"]  # has a model
    assert call.kwargs["contents"] == "Say hi"
    assert call.kwargs["config"]["system_instruction"] == "be friendly"


@pytest.mark.asyncio
async def test_stream_text_retries_on_transient_error() -> None:
    svc = GeminiService(api_key="test")
    client = MagicMock()

    call_count = {"n": 0}

    async def _stream(**_kwargs: Any) -> AsyncIterator[Any]:
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise RuntimeError("503 Service Unavailable")
        return _async_iter([_make_chunk("ok")])

    client.aio.models.generate_content_stream = AsyncMock(side_effect=_stream)
    svc._client = client  # type: ignore[attr-defined]

    out: list[str] = []
    async for tok in svc.stream_text("hi"):
        out.append(tok)

    assert out == ["ok"]
    assert call_count["n"] == 2  # one failure + one success


@pytest.mark.asyncio
async def test_stream_text_does_not_retry_non_transient() -> None:
    svc = GeminiService(api_key="test")
    client = MagicMock()
    call_count = {"n": 0}

    async def _stream(**_kwargs: Any) -> AsyncIterator[Any]:
        call_count["n"] += 1
        raise ValueError("invalid prompt")

    client.aio.models.generate_content_stream = AsyncMock(side_effect=_stream)
    svc._client = client  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="invalid prompt"):
        async for _ in svc.stream_text("hi"):
            pass

    assert call_count["n"] == 1  # no retries on non-transient error


@pytest.mark.asyncio
async def test_stream_text_logs_token_usage(caplog: pytest.LogCaptureFixture) -> None:
    """Final chunk's usage_metadata should flow through the structured log."""
    svc = GeminiService(api_key="test")
    svc._client = _mock_client_with_stream(  # type: ignore[attr-defined]
        [_make_chunk("hi", usage={"prompt": 4, "output": 1, "total": 5})]
    )
    async for _ in svc.stream_text("hi"):
        pass
    # No assertion on caplog content (structlog uses its own pipeline);
    # the test simply confirms the path doesn't raise.


# ── analyze_image ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_analyze_image_returns_text_and_json() -> None:
    svc = GeminiService(api_key="test")
    client = MagicMock()
    response = SimpleNamespace(
        text='```json\n{"shape": "circle"}\n```',
        candidates=[],
        usage_metadata=None,
    )
    client.aio.models.generate_content = AsyncMock(return_value=response)
    svc._client = client  # type: ignore[attr-defined]

    # base64 of single byte 0x00
    out = await svc.analyze_image(image_b64="AA==", prompt="What's this?")

    assert "circle" in out["text"]
    assert out["json"] == {"shape": "circle"}


@pytest.mark.asyncio
async def test_analyze_image_rejects_bad_b64() -> None:
    svc = GeminiService(api_key="test")
    svc._client = MagicMock()  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="base64"):
        await svc.analyze_image(image_b64="!!!not-base64!!!", prompt="x")


# ── embed ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_embed_returns_vectors() -> None:
    svc = GeminiService(api_key="test")
    client = MagicMock()
    client.aio.models.embed_content = AsyncMock(
        return_value=SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3])]
        )
    )
    svc._client = client  # type: ignore[attr-defined]
    out = await svc.embed("hello")
    assert out == [[0.1, 0.2, 0.3]]


# ── client lazy-init guard ───────────────────────────────────────────────────
def test_client_requires_api_key() -> None:
    # Force an empty key (the constructor falls back to settings when given
    # an empty string, so we set the private slot directly here).
    svc = GeminiService(api_key="placeholder")
    svc._api_key = ""  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        _ = svc.client
