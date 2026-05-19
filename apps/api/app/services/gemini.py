"""Gemini AI service wrapper.

Uses the **new** `google-genai` SDK (NOT the deprecated `google-generativeai`).

Key entry points:
    - `stream_text` — async generator that yields tokens for SSE Q&A.
    - `analyze_image` — vision call that returns parsed JSON when possible.
    - `embed`         — embeddings via `gemini-embedding-001`.
    - `get_live_client` — async context manager used by the /ws/voice
      bridge (Gemini Live API — bidirectional audio).

Transient errors (5xx, rate limits) are retried with exponential backoff.
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


# ── Retry policy ──────────────────────────────────────────────────────────────
_RETRYABLE_PATTERNS = (
    "rate limit",
    "429",
    "500",
    "502",
    "503",
    "504",
    "deadline exceeded",
    "unavailable",
    "internal error",
)


def _is_retryable(exc: BaseException) -> bool:
    """Heuristic: retry on transient API failures.

    The new SDK raises a variety of error classes (`APIError`, network
    exceptions, etc.) — we inspect the message to stay loosely coupled.
    """
    msg = str(exc).lower()
    return any(p in msg for p in _RETRYABLE_PATTERNS)


def _retry_policy() -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )


# ── JSON extraction helper ────────────────────────────────────────────────────
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _coerce_json(text: str) -> dict[str, Any] | list[Any] | None:
    """Best-effort: parse a JSON object/array from a model response.

    Looks for a fenced ```json``` block first, falls back to the first
    `{ … }` or `[ … ]` substring. Returns ``None`` when no JSON is found.
    """
    if not text:
        return None
    m = _JSON_BLOCK_RE.search(text)
    candidate = m.group(1) if m else None
    if candidate is None:
        # Greedy capture of the outermost object/array.
        start = next((i for i, c in enumerate(text) if c in "{["), None)
        if start is None:
            return None
        end = text.rfind("}" if text[start] == "{" else "]")
        if end <= start:
            return None
        candidate = text[start : end + 1]

    try:
        return json.loads(candidate)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return None


def _extract_inline_data(response: Any, kind: str) -> bytes | None:
    """Pull the first inline `{kind}/*` part's raw bytes from a genai response.

    Image and TTS models return their output as an `inline_data` part on a
    candidate; its `data` is raw bytes (new SDK) or base64 text (older
    shapes). `kind` is the mime prefix to match — `"image"` or `"audio"`.
    """
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            mime = str(getattr(inline, "mime_type", "") or "")
            data = getattr(inline, "data", None)
            if data and mime.startswith(f"{kind}/"):
                if isinstance(data, str):
                    return base64.b64decode(data)
                return bytes(data)
    return None


# ── Service ───────────────────────────────────────────────────────────────────
class GeminiService:
    """Thin async wrapper around `google.genai.Client`."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.gemini_api_key.get_secret_value()
        self._client: Any | None = None  # lazy — avoid import-time auth

    # ---- client lifecycle ----------------------------------------------------
    @property
    def client(self) -> Any:
        """Lazily-constructed `genai.Client` instance."""
        if self._client is None:
            # Imported lazily so unit tests can run without the network.
            from google import genai  # type: ignore[import-not-found]

            if not self._api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY is not set — refusing to instantiate Gemini client."
                )
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    # ---- helpers -------------------------------------------------------------
    def _log_usage(self, response: Any, *, op: str) -> None:
        """Emit a structured log line with token counts when available."""
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return
        log.info(
            "gemini_usage",
            op=op,
            prompt_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            total_tokens=getattr(usage, "total_token_count", None),
        )

    @staticmethod
    def _extract_text(chunk: Any) -> str:
        """Pull plaintext from a streaming chunk regardless of SDK shape."""
        text = getattr(chunk, "text", None)
        if text:
            return str(text)
        # Fallback: walk candidates -> content -> parts -> text
        candidates = getattr(chunk, "candidates", None) or []
        out: list[str] = []
        for c in candidates:
            content = getattr(c, "content", None)
            for part in getattr(content, "parts", None) or []:
                t = getattr(part, "text", None)
                if t:
                    out.append(str(t))
        return "".join(out)

    # ---- core ops ------------------------------------------------------------
    async def stream_text(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream text tokens for an SSE-style Q&A response.

        Yields raw text fragments — callers wrap them in `data:` envelopes.
        """
        model_name = model or settings.gemini_model_text

        # Compose contents — the new SDK accepts a plain string OR a list of parts.
        contents = prompt
        config: dict[str, Any] = {}
        if system:
            config["system_instruction"] = system

        async def _run() -> AsyncIterator[Any]:
            kwargs: dict[str, Any] = {"model": model_name, "contents": contents}
            if config:
                kwargs["config"] = config
            # `generate_content_stream` returns an async iterator in the new SDK.
            return await self.client.aio.models.generate_content_stream(**kwargs)

        async for attempt in _retry_policy():
            with attempt:
                stream = await _run()
                last_chunk: Any = None
                async for chunk in stream:
                    last_chunk = chunk
                    piece = self._extract_text(chunk)
                    if piece:
                        yield piece
                if last_chunk is not None:
                    self._log_usage(last_chunk, op="stream_text")
                return  # success — exit retry loop

    async def analyze_image(
        self,
        image_b64: str,
        prompt: str,
        mime_type: str = "image/png",
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send an image + prompt to the vision model.

        Returns a dict with:
            { "text": <raw model output>, "json": <parsed JSON or None> }
        """
        model_name = model or settings.gemini_model_vision

        # The new SDK accepts inline Part dicts in `contents`.
        try:
            image_bytes = base64.b64decode(image_b64, validate=True)
        except (ValueError, base64.binascii.Error) as e:
            raise ValueError("image_b64 must be a valid base64 string") from e

        contents = [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": image_bytes}},
                    {"text": prompt},
                ],
            }
        ]

        async for attempt in _retry_policy():
            with attempt:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                )
                self._log_usage(response, op="analyze_image")
                text = self._extract_text(response) or getattr(response, "text", "") or ""
                return {"text": text, "json": _coerce_json(text)}

        # tenacity always raises on exhaustion — this is just for type-checkers.
        raise RuntimeError("analyze_image: retry loop exhausted without yielding")

    async def generate_image(
        self,
        prompt: str,
        model: str | None = None,
    ) -> bytes:
        """Generate a single image with Nano Banana 2 — returns PNG/JPEG bytes.

        Used for course cover art (`model-strategy.md` §4). Raises on failure;
        callers treat cover generation as best-effort and swallow the error.
        """
        model_name = model or settings.gemini_model_image

        async for attempt in _retry_policy():
            with attempt:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={"response_modalities": ["TEXT", "IMAGE"]},
                )
                self._log_usage(response, op="generate_image")
                data = _extract_inline_data(response, "image")
                if data:
                    return data
                raise RuntimeError("generate_image: model returned no image part")

        # tenacity always raises on exhaustion — this is just for type-checkers.
        raise RuntimeError("generate_image: retry loop exhausted without yielding")

    async def synthesize_speech(
        self,
        text: str,
        voice: str,
        model: str | None = None,
    ) -> bytes:
        """Read `text` aloud with a dedicated TTS model — returns raw PCM.

        One-shot `generate_content` call against `gemini-3.1-flash-tts-preview`
        (`model-strategy.md` §3b) — the model reads verbatim, so no system
        prompt / "explain" hack is needed. Output is 24 kHz 16-bit mono PCM
        (the caller wraps it as WAV). Raises on failure.
        """
        model_name = model or settings.gemini_model_tts

        async for attempt in _retry_policy():
            with attempt:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=text,
                    config={
                        "response_modalities": ["AUDIO"],
                        "speech_config": {
                            "voice_config": {
                                "prebuilt_voice_config": {"voice_name": voice}
                            }
                        },
                    },
                )
                self._log_usage(response, op="synthesize_speech")
                data = _extract_inline_data(response, "audio")
                if data:
                    return data
                raise RuntimeError(
                    "synthesize_speech: model returned no audio part"
                )

        # tenacity always raises on exhaustion — this is just for type-checkers.
        raise RuntimeError("synthesize_speech: retry loop exhausted")

    async def generate_from_pdfs(
        self,
        pdfs: list[bytes],
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        response_schema: Any | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        """Send one or more PDFs + a prompt as a single multimodal request.

        Used by the teacher-authoring comprehension call (`segment.py`): the
        whole unit's normalized PDFs go inline as `application/pdf` parts in
        ONE `contents` message, so the model reads every material together.
        The Fluids PDF is ~3.4 MB — well under the inline-data limit.

        When `response_schema` is given the new SDK parses the response into
        that Pydantic model and exposes it on `.parsed`.

        Returns a dict:
            { "text": <raw model output>, "json": <parsed JSON or None> }
        `json` is the parsed object (`.parsed` when a schema was set, else a
        best-effort JSON coercion of the text).
        """
        model_name = model or settings.gemini_model_text

        parts: list[dict[str, Any]] = [
            {"inline_data": {"mime_type": "application/pdf", "data": pdf}}
            for pdf in pdfs
        ]
        parts.append({"text": prompt})
        contents = [{"role": "user", "parts": parts}]

        config: dict[str, Any] = {"temperature": temperature}
        if system:
            config["system_instruction"] = system
        if response_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = response_schema

        async for attempt in _retry_policy():
            with attempt:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                self._log_usage(response, op="generate_from_pdfs")
                parsed = getattr(response, "parsed", None)
                text = (
                    self._extract_text(response)
                    or getattr(response, "text", "")
                    or ""
                )
                return {
                    "text": text,
                    "json": parsed if parsed is not None else _coerce_json(text),
                }

        raise RuntimeError("generate_from_pdfs: retry loop exhausted without yielding")

    async def embed(
        self,
        text: str | list[str],
        output_dim: int = 768,
    ) -> list[list[float]]:
        """Compute embeddings via `gemini-embedding-001`.

        gemini-embedding-001 produces 3072-dim vectors by default; we request 768
        to match the `vector(768)` column in the `lesson_embeddings` table.
        Pass `output_dim=3072` if you need the full embedding.

        Returns a list-of-vectors (one per input).
        """
        items = [text] if isinstance(text, str) else list(text)

        async for attempt in _retry_policy():
            with attempt:
                response = await self.client.aio.models.embed_content(
                    model=settings.gemini_model_embed,
                    contents=items,
                    config={"output_dimensionality": output_dim},
                )
                # New SDK returns `.embeddings` (list with `.values` each).
                embeddings = getattr(response, "embeddings", None) or []
                return [list(getattr(e, "values", e)) for e in embeddings]

        raise RuntimeError("embed: retry loop exhausted without yielding")

    # ---- Live API (voice WebSocket bridge) -----------------------------------
    def get_live_client(
        self,
        model: str | None = None,
        system_instruction: str | None = None,
        response_modalities: list[str] | None = None,
        voice_name: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        """Return an async context-manager for a Gemini Live API session.

        Usage (inside `app/ws/voice.py`):

            async with gemini.get_live_client(
                system_instruction="You are Aria…",
                response_modalities=["AUDIO"],
            ) as session:
                await session.send_realtime_input(audio=...)
                async for response in session.receive():
                    ...

        `response_modalities` defaults to `["AUDIO"]` for the native-audio model
        (the API rejects empty config with "Cannot extract voices from a non-audio
        request"). Override to `["TEXT"]` for transcript-only sessions.

        Any extra fields in `config` are merged on top of the assembled config.
        """
        model_name = model or settings.gemini_model_live

        cfg: dict[str, Any] = {
            "response_modalities": response_modalities or ["AUDIO"],
            # Stream a live transcript of the student's speech — Gemini Live
            # surfaces it as `input_transcription` on each response's
            # `server_content`; the voice bridge relays it as `transcript`
            # frames so the classroom can show what the student is saying.
            "input_audio_transcription": {},
        }
        if system_instruction:
            cfg["system_instruction"] = system_instruction
        if voice_name:
            # speech_config shape per the new SDK
            cfg["speech_config"] = {
                "voice_config": {"prebuilt_voice_config": {"voice_name": voice_name}},
            }
        if config:
            cfg.update(config)

        return self.client.aio.live.connect(model=model_name, config=cfg)


# ── Module singleton ─────────────────────────────────────────────────────────
_gemini_singleton: GeminiService | None = None


def get_gemini() -> GeminiService:
    """Return a cached `GeminiService` instance. FastAPI-dependency friendly."""
    global _gemini_singleton
    if _gemini_singleton is None:
        _gemini_singleton = GeminiService()
    return _gemini_singleton


@contextlib.asynccontextmanager
async def gemini_scope() -> AsyncIterator[GeminiService]:
    """Async context manager — useful for short-lived task wrappers."""
    yield get_gemini()
