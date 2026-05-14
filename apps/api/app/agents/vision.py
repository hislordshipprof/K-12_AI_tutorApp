"""Vision agent — analyzes student chalkboard sketches via Gemini multimodal.

The :class:`VisionAgent` wraps :class:`~app.services.gemini.GeminiService` and
exposes :meth:`analyze_sketch`, an async generator that yields a structured
event stream:

    {"type": "recognition", "shape": ..., "confidence": ..., "intent": ...}
    {"type": "chunk", "delta": "..."}      # Socratic message tokens
    {"type": "done"}
    {"type": "error", "message": "..."}    # on Gemini failure

It also exports a pure-Python heuristic stroke recognizer,
:func:`recognize_stroke_geometry`, ported from the prototype's
``recognizeStroke`` JS implementation. That utility is useful when the client
sends raw stroke points alongside (or instead of) a rendered PNG.
"""

from __future__ import annotations

import base64
import json
import math
import re
from collections.abc import AsyncGenerator, Iterator
from typing import Any

# IMPORTANT: this module deliberately avoids ``from app.agents …`` imports —
# the package ``__init__`` is in flux while sibling agents are being built.
from app.core.logging import get_logger
from app.services.gemini import GeminiService

log = get_logger(__name__)


# ── Prompts ───────────────────────────────────────────────────────────────────
VISION_SYSTEM = (
    "You are Aria, a Socratic high school physics tutor.\n"
    "Look at the student's sketch on a chalkboard. Identify what they likely drew "
    "in physics terms (wave, line, equation, arrow, etc.). Respond by:\n"
    "1. First emitting a JSON line: "
    '{"shape": "...", "confidence": 0.0-1.0, "intent": "..."}\n'
    "2. Then emitting a SHORT Socratic message that acknowledges what you see and "
    "asks them to explain their thinking. NEVER give the answer."
)


_KNOWN_SHAPES = (
    "wave",
    "line",
    "horizontal-line",
    "vertical-line",
    "diagonal-line",
    "equation",
    "circle",
    "arrow",
    "writing",
    "curve",
    "sketch",
    "other",
)


def _build_user_prompt(topic_name: str | None, question: str | None) -> str:
    """Compose the per-request user prompt."""
    ctx = f" The current lesson is about: {topic_name}." if topic_name else ""
    qctx = f' The student asked: "{question}".' if question else ""
    return (
        f"{ctx}{qctx}\n\n"
        "Identify what the student drew. Reply in this exact format:\n"
        'Line 1 (JSON only): {"shape": '
        '"wave|line|equation|circle|arrow|writing|other", '
        '"confidence": 0.0-1.0, "intent": "short description"}\n'
        "Then a blank line, then a SHORT Socratic message (2-3 sentences) asking "
        "the student to explain their drawing. Never give the answer."
    )


# ── Helpers ───────────────────────────────────────────────────────────────────
_JSON_LINE_RE = re.compile(r"\{[^\n{}]*\}")


def _parse_recognition(text: str) -> tuple[dict[str, Any] | None, str]:
    """Pull the first balanced JSON object out of ``text``.

    Returns ``(recognition_dict | None, remaining_socratic_message)``.

    Tries strategies in order:
        1. The first line that starts with ``{`` is parsed as JSON.
        2. The first ``{ ... }`` substring on any line is parsed.
        3. If both fail, returns ``(None, original_text)``.
    """
    if not text:
        return None, ""

    lines = text.splitlines()
    for i, raw in enumerate(lines):
        stripped = raw.strip().lstrip("`").rstrip("`").strip()
        # Strip possible json fence
        if stripped.startswith("```"):
            continue
        if stripped.startswith("{"):
            # Try full-line JSON first
            try:
                obj = json.loads(stripped)
                rest = "\n".join(lines[i + 1 :]).strip()
                if isinstance(obj, dict):
                    return obj, rest
            except json.JSONDecodeError:
                pass

    # Fallback: greedy first {...} match anywhere in the text.
    m = _JSON_LINE_RE.search(text)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                # Strip the JSON span from the text for the Socratic remainder.
                rest = (text[: m.start()] + text[m.end() :]).strip()
                return obj, rest
        except json.JSONDecodeError:
            pass

    return None, text.strip()


def _normalize_recognition(d: dict[str, Any]) -> dict[str, Any]:
    """Coerce loose model output into a canonical recognition payload."""
    shape = str(d.get("shape") or "other").strip().lower()
    if shape not in _KNOWN_SHAPES:
        shape = "other"

    try:
        confidence = float(d.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    intent = str(d.get("intent") or "").strip()
    return {"shape": shape, "confidence": confidence, "intent": intent}


# ── Agent ─────────────────────────────────────────────────────────────────────
class VisionAgent:
    """Aria's eyes — multimodal sketch analyzer."""

    def __init__(self, gemini: GeminiService) -> None:
        self.gemini = gemini

    async def analyze_sketch(
        self,
        png_bytes: bytes,
        topic_name: str | None = None,
        question: str | None = None,
        mime_type: str = "image/png",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield a structured event stream for a single sketch analysis.

        Events:
            ``{"type": "recognition", "shape": ..., "confidence": ..., "intent": ...}``
            ``{"type": "chunk", "delta": "..."}``  (Socratic message, word-boundary)
            ``{"type": "done"}``
            ``{"type": "error", "message": ...}``  (on Gemini failure)
        """
        b64 = base64.b64encode(png_bytes).decode("ascii")
        prompt = _build_user_prompt(topic_name, question)

        log.info(
            "vision_analyze_start",
            bytes=len(png_bytes),
            mime=mime_type,
            has_question=bool(question),
            has_topic=bool(topic_name),
        )

        try:
            result = await self.gemini.analyze_image(
                image_b64=b64,
                prompt=f"{VISION_SYSTEM}\n\n{prompt}",
                mime_type=mime_type,
            )
        except Exception as e:  # noqa: BLE001 — surface as an SSE error event
            log.exception("vision_gemini_failed")
            yield {"type": "error", "message": str(e)}
            yield {"type": "done"}
            return

        text = (result.get("text") or "").strip()

        recognition, socratic_msg = _parse_recognition(text)
        if recognition is None and isinstance(result.get("json"), dict):
            # GeminiService's _coerce_json picked it up — use that.
            recognition = result["json"]

        if recognition:
            payload = _normalize_recognition(recognition)
            log.info("vision_recognition", **payload)
            yield {"type": "recognition", **payload}

        # Stream the Socratic message in nice word-boundary chunks.
        for piece in self._chunkify(socratic_msg or text):
            yield {"type": "chunk", "delta": piece}

        yield {"type": "done"}

    @staticmethod
    def _chunkify(text: str, chunk_size: int = 50) -> Iterator[str]:
        """Yield word-boundary chunks of approximately ``chunk_size`` chars."""
        if not text:
            return
        words = text.split(" ")
        buf: list[str] = []
        size = 0
        for w in words:
            # +1 accounts for the space we'll join with.
            if size + len(w) + 1 > chunk_size and buf:
                yield " ".join(buf)
                buf = [w]
                size = len(w)
            else:
                buf.append(w)
                size += len(w) + 1
        if buf:
            yield " ".join(buf)


# ── Heuristic stroke recognizer (geometric fallback) ─────────────────────────
def recognize_stroke_geometry(points: list[tuple[float, float]]) -> str:
    """Classify a single stroke by its geometry.

    Ported from the prototype's ``recognizeStroke`` JS function. Returns one of:

        ``'wave' | 'horizontal-line' | 'vertical-line' | 'diagonal-line' |
          'curve' | 'circle' | 'writing' | 'sketch'``

    or ``'sketch'`` for the default catch-all.
    """
    if not points or len(points) < 2:
        return "sketch"

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x
    h = max_y - min_y
    aspect = w / max(1.0, h)

    # Tiny mark = probably writing component (digit/letter/dot)
    if max(w, h) < 40 and len(points) < 16:
        return "writing"

    # Count direction changes in Y to detect wave-ness.
    y_changes = 0
    last_dy = 0
    for i in range(2, len(points)):
        dy = ys[i] - ys[i - 1]
        if abs(dy) < 0.5:
            continue
        s = 1 if dy > 0 else (-1 if dy < 0 else 0)
        if last_dy != 0 and s != last_dy:
            y_changes += 1
        last_dy = s

    if y_changes >= 3 and w > 60:
        return "wave"
    if y_changes >= 1 and w > 40 and w > h * 1.5:
        return "curve"

    # Mostly straight
    if aspect > 4 and h < 30:
        return "horizontal-line"
    if aspect < 0.25 and w < 30:
        return "vertical-line"
    if max(w, h) > 50 and y_changes < 1:
        return "diagonal-line"

    # Closed-ish? start/end close + reasonable size.
    dx = points[0][0] - points[-1][0]
    dy_close = points[0][1] - points[-1][1]
    closing_dist = math.hypot(dx, dy_close)
    span = max(w, h)
    if span > 30 and closing_dist < span * 0.3:
        return "circle"

    return "sketch"


def aggregate_recognition(shapes: list[str | None]) -> str | None:
    """Roll up a stream of per-stroke labels into a coarse session signal.

    Mirrors the prototype's ``aggregateRecognition`` helper:
    if the last six strokes contain three+ ``writing`` marks → ``writing-cluster``,
    otherwise return the most recent non-null shape.
    """
    if not shapes:
        return None
    recent = shapes[-6:]
    writing = sum(1 for s in recent if s == "writing")
    if writing >= 3:
        return "writing-cluster"
    # Most recent non-null.
    for s in reversed(shapes):
        if s:
            return s
    return None


__all__ = [
    "VISION_SYSTEM",
    "VisionAgent",
    "aggregate_recognition",
    "recognize_stroke_geometry",
]
