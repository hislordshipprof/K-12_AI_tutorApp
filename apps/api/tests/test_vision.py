"""Tests for ``VisionAgent`` + the ``/v1/sessions/{id}/sketch`` endpoint.

All Gemini and Supabase calls are mocked — no network is touched.
"""

from __future__ import annotations

import base64
import io
import json
import math
import struct
import sys
import zlib
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────
def _make_png(width: int = 8, height: int = 8) -> bytes:
    """Hand-roll a minimal valid PNG (all-zero pixels) — no Pillow dependency."""

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    # IDAT: each row prefixed with filter byte 0, then width*3 bytes of pixel.
    raw = b""
    for _ in range(height):
        raw += b"\x00" + b"\x00\x00\x00" * width
    idat = zlib.compress(raw)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _load_vision_module() -> Any:
    """Import ``app.agents.vision`` even when sibling agents aren't ready.

    Mirrors the loader used inside ``app/api/v1/sketch.py``.
    """
    import importlib
    import importlib.util
    import os

    cached = sys.modules.get("app.agents.vision")
    if cached is not None:
        return cached
    try:
        return importlib.import_module("app.agents.vision")
    except Exception:
        here = os.path.dirname(os.path.abspath(__file__))
        vision_path = os.path.abspath(
            os.path.join(here, "..", "app", "agents", "vision.py")
        )
        spec = importlib.util.spec_from_file_location(
            "app.agents.vision", vision_path
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["app.agents.vision"] = mod
        spec.loader.exec_module(mod)
        return mod


vision = _load_vision_module()
VisionAgent = vision.VisionAgent
recognize_stroke_geometry = vision.recognize_stroke_geometry
aggregate_recognition = vision.aggregate_recognition


# ── VisionAgent unit tests ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_analyze_sketch_emits_recognition_then_chunks_then_done() -> None:
    """Happy path: JSON line + Socratic message → recognition + chunk + done."""
    gemini = AsyncMock()
    gemini.analyze_image = AsyncMock(
        return_value={
            "text": (
                '{"shape": "wave", "confidence": 0.92, "intent": "transverse wave"}\n'
                "\n"
                "Nice curve! Tell me what changes when you stretch the wavelength "
                "but keep the amplitude the same."
            ),
            "json": {"shape": "wave", "confidence": 0.92, "intent": "transverse wave"},
        }
    )

    agent = VisionAgent(gemini)
    events: list[dict[str, Any]] = []
    async for ev in agent.analyze_sketch(b"\x89PNG-data", question="is this a wave?"):
        events.append(ev)

    # First event must be recognition with normalized fields.
    assert events[0]["type"] == "recognition"
    assert events[0]["shape"] == "wave"
    assert 0.0 <= events[0]["confidence"] <= 1.0
    assert events[0]["intent"]

    # Then one or more chunks.
    chunks = [e for e in events if e["type"] == "chunk"]
    assert chunks, "expected at least one chunk event"
    full_msg = " ".join(c["delta"] for c in chunks)
    assert "wavelength" in full_msg.lower()

    # Last event must be done.
    assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_analyze_sketch_base64_encodes_image() -> None:
    """The agent must base64-encode raw PNG bytes before calling Gemini."""
    captured: dict[str, Any] = {}

    async def _fake_analyze(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"text": '{"shape":"line","confidence":0.5,"intent":"x"}\n\nWhy?', "json": None}

    gemini = AsyncMock()
    gemini.analyze_image = AsyncMock(side_effect=_fake_analyze)

    agent = VisionAgent(gemini)
    raw = b"raw-png-bytes-here"
    async for _ in agent.analyze_sketch(raw):
        pass

    assert "image_b64" in captured
    decoded = base64.b64decode(captured["image_b64"])
    assert decoded == raw
    assert captured["mime_type"] == "image/png"


@pytest.mark.asyncio
async def test_analyze_sketch_emits_error_when_gemini_fails() -> None:
    """If Gemini raises, the agent should yield an error then a done event."""
    gemini = AsyncMock()
    gemini.analyze_image = AsyncMock(side_effect=RuntimeError("boom"))

    agent = VisionAgent(gemini)
    events: list[dict[str, Any]] = []
    async for ev in agent.analyze_sketch(b"\x89PNG-data"):
        events.append(ev)

    assert any(e["type"] == "error" and "boom" in e["message"] for e in events)
    assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_analyze_sketch_normalizes_unknown_shape_to_other() -> None:
    gemini = AsyncMock()
    gemini.analyze_image = AsyncMock(
        return_value={
            "text": '{"shape": "spaceship", "confidence": 1.5, "intent": "??"}\n\nWhat is this?',
            "json": None,
        }
    )
    agent = VisionAgent(gemini)
    events = [ev async for ev in agent.analyze_sketch(b"x")]
    recog = next(e for e in events if e["type"] == "recognition")
    assert recog["shape"] == "other"
    # Confidence clamped to [0, 1].
    assert 0.0 <= recog["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_analyze_sketch_handles_missing_json_block() -> None:
    """When Gemini doesn't emit a JSON line, the entire reply is the chunk."""
    gemini = AsyncMock()
    gemini.analyze_image = AsyncMock(
        return_value={"text": "Tell me what you see in your sketch.", "json": None}
    )
    agent = VisionAgent(gemini)
    events = [ev async for ev in agent.analyze_sketch(b"x")]
    types = [e["type"] for e in events]
    assert "recognition" not in types  # no recognition event when no JSON
    assert "done" in types
    chunks = [e for e in events if e["type"] == "chunk"]
    assert any("Tell me what you see" in c["delta"] for c in chunks)


@pytest.mark.asyncio
async def test_analyze_sketch_includes_topic_and_question_in_prompt() -> None:
    captured: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"text": "ok", "json": None}

    gemini = AsyncMock()
    gemini.analyze_image = AsyncMock(side_effect=_fake)
    agent = VisionAgent(gemini)
    async for _ in agent.analyze_sketch(
        b"x", topic_name="Waves & Oscillations", question="amplitude?"
    ):
        pass

    prompt = captured["prompt"]
    assert "Waves & Oscillations" in prompt
    assert "amplitude?" in prompt


# ── Geometric stroke recognizer ──────────────────────────────────────────────
def test_recognize_wave_from_sine_points() -> None:
    pts = [(x, 100 + 30 * math.sin(x / 10)) for x in range(0, 200, 2)]
    assert recognize_stroke_geometry(pts) == "wave"


def test_recognize_horizontal_line() -> None:
    pts = [(x, 50) for x in range(0, 200, 5)]
    assert recognize_stroke_geometry(pts) == "horizontal-line"


def test_recognize_vertical_line() -> None:
    pts = [(50, y) for y in range(0, 200, 5)]
    assert recognize_stroke_geometry(pts) == "vertical-line"


def test_recognize_diagonal_line() -> None:
    pts = [(x, x) for x in range(0, 200, 4)]
    assert recognize_stroke_geometry(pts) == "diagonal-line"


def test_recognize_circle_closed_path() -> None:
    pts = [
        (50 + 40 * math.cos(t), 50 + 40 * math.sin(t))
        for t in [i * math.pi / 16 for i in range(33)]  # closes back to start
    ]
    assert recognize_stroke_geometry(pts) == "circle"


def test_recognize_writing_for_tiny_marks() -> None:
    pts = [(10, 10), (11, 12), (10, 11), (12, 13)]
    assert recognize_stroke_geometry(pts) == "writing"


def test_recognize_returns_sketch_when_ambiguous() -> None:
    # Very few points spread far apart, no clear pattern.
    pts = [(0, 0), (10, 10)]
    assert recognize_stroke_geometry(pts) in {"sketch", "writing", "diagonal-line"}


def test_recognize_empty_returns_sketch() -> None:
    assert recognize_stroke_geometry([]) == "sketch"
    assert recognize_stroke_geometry([(1, 1)]) == "sketch"


def test_aggregate_recognition_returns_writing_cluster() -> None:
    shapes = ["writing", "writing", "writing", "wave", "writing"]
    assert aggregate_recognition(shapes) == "writing-cluster"


def test_aggregate_recognition_returns_most_recent() -> None:
    shapes = ["wave", "line", "circle"]
    assert aggregate_recognition(shapes) == "circle"


def test_aggregate_recognition_handles_empty() -> None:
    assert aggregate_recognition([]) is None
    assert aggregate_recognition([None, None]) is None


# ── Chunkifier ───────────────────────────────────────────────────────────────
def test_chunkify_yields_word_boundary_pieces() -> None:
    text = "Aria asks: what changes when you stretch the wavelength while keeping amplitude fixed?"
    pieces = list(VisionAgent._chunkify(text, chunk_size=25))
    assert pieces, "expected non-empty chunks"
    # No piece exceeds chunk_size by more than one word's worth.
    for p in pieces:
        assert len(p) <= 60
    # Reassembled, the text matches.
    assert " ".join(pieces) == text


def test_chunkify_empty_string() -> None:
    assert list(VisionAgent._chunkify("")) == []


# ── Endpoint integration tests ───────────────────────────────────────────────
def _mock_gemini_returning(text: str) -> AsyncMock:
    mock = AsyncMock()
    mock.analyze_image = AsyncMock(return_value={"text": text, "json": None})
    return mock


def test_sketch_endpoint_rejects_non_image(client: Any, dev_headers: dict[str, str]) -> None:
    r = client.post(
        "/v1/sessions/00000000-0000-0000-0000-000000000001/sketch",
        headers=dev_headers,
        files={"image": ("note.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 400


def test_sketch_endpoint_rejects_oversize_image(
    client: Any, dev_headers: dict[str, str]
) -> None:
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (9 * 1024 * 1024)
    r = client.post(
        "/v1/sessions/00000000-0000-0000-0000-000000000001/sketch",
        headers=dev_headers,
        files={"image": ("big.png", payload, "image/png")},
    )
    assert r.status_code == 413


def test_sketch_endpoint_rejects_empty_body(
    client: Any, dev_headers: dict[str, str]
) -> None:
    r = client.post(
        "/v1/sessions/00000000-0000-0000-0000-000000000001/sketch",
        headers=dev_headers,
        files={"image": ("empty.png", b"", "image/png")},
    )
    assert r.status_code == 400


def test_sketch_endpoint_streams_sse_events(
    client: Any, dev_headers: dict[str, str]
) -> None:
    """End-to-end happy path: PNG in → recognition + chunk + done SSE events."""
    from app.main import app
    from app.services.gemini import get_gemini

    png = _make_png()

    fake = _mock_gemini_returning(
        '{"shape": "circle", "confidence": 0.8, "intent": "a closed loop"}\n\n'
        "What property of a circle is constant for every point on its edge?"
    )

    # Override the FastAPI dependency for `get_gemini` and patch the
    # background sketch-save coroutine so the test never touches Supabase.
    app.dependency_overrides[get_gemini] = lambda: fake
    try:
        with patch(
            "app.api.v1.sketch._persist_sketch_row", new_callable=AsyncMock
        ):
            r = client.post(
                "/v1/sessions/00000000-0000-0000-0000-000000000001/sketch",
                headers=dev_headers,
                files={"image": ("c.png", png, "image/png")},
                data={"question": "is this a circle?"},
            )
    finally:
        app.dependency_overrides.pop(get_gemini, None)

    assert r.status_code == 200
    body = r.text
    # Parse SSE events.
    events: list[dict[str, Any]] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))

    types = [e["type"] for e in events]
    assert "recognition" in types
    assert "chunk" in types
    assert types[-1] == "done"

    recog = next(e for e in events if e["type"] == "recognition")
    assert recog["shape"] == "circle"
    assert recog["confidence"] == pytest.approx(0.8)
