"""Structured-output lesson generator (B2).

Calls ``gemini-pro-latest`` with ``response_schema=LessonContent`` so the
model output lands as a typed Pydantic object instead of free-form text we
have to JSON-coerce. Persona + 8-step rubric live in
``app.content.prompts``; this module is the thin async client.

Retries: tenacity, 3 attempts, exponential backoff. The same retryable-error
heuristic as ``services.gemini`` (5xx + rate-limit messages).
"""

from __future__ import annotations

from typing import Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.content.chunker import Chunk
from app.content.prompts import (
    LESSON_GENERATION_SYSTEM_PROMPT,
    LESSON_GENERATION_USER_PROMPT,
)
from app.content.schema import LessonContent
from app.core.config import settings
from app.core.logging import get_logger
from app.services.gemini import GeminiService

log = get_logger(__name__)

_RETRYABLE = (
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
    msg = str(exc).lower()
    return any(p in msg for p in _RETRYABLE)


def _retry_policy() -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )


class LessonGenerator:
    """Async wrapper around ``gemini-pro-latest`` for 8-step lesson generation."""

    def __init__(
        self,
        gemini: GeminiService | None = None,
        model: str | None = None,
    ) -> None:
        self._gemini = gemini
        self._model = model or settings.gemini_model_pro

    @property
    def gemini(self) -> GeminiService:
        if self._gemini is None:
            # Lazy default — keeps unit tests free of API-key requirements
            # when they inject their own stubbed service.
            self._gemini = GeminiService()
        return self._gemini

    async def generate(
        self,
        topic_name: str,
        required_terms: list[str],
        required_equations: list[str],
        source_chunks: list[Chunk],
        *,
        extra_instructions: str | None = None,
        temperature: float = 0.6,
    ) -> LessonContent:
        """Produce one 8-step ``LessonContent`` for ``topic_name``.

        ``extra_instructions`` is appended to the user prompt — the CLI uses
        this on validator-retry to inject the specific failures (missing
        terms / equations) so the model can correct course.
        """
        user_prompt = LESSON_GENERATION_USER_PROMPT(
            topic_name=topic_name,
            required_terms=required_terms,
            required_equations=required_equations,
            source_chunks=source_chunks,
            extra_instructions=extra_instructions,
        )

        client = self.gemini.client

        config: dict[str, Any] = {
            "system_instruction": LESSON_GENERATION_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": LessonContent,
            "temperature": temperature,
        }

        log.info(
            "content_generate_start",
            model=self._model,
            topic=topic_name,
            required_terms_n=len(required_terms),
            required_equations_n=len(required_equations),
            chunks_n=len(source_chunks),
        )

        async for attempt in _retry_policy():
            with attempt:
                response = await client.aio.models.generate_content(
                    model=self._model,
                    contents=user_prompt,
                    config=config,
                )
                # The new google-genai SDK exposes the parsed Pydantic object
                # on `.parsed` when `response_schema` is set. Fall back to
                # JSON-parsing `.text` if the SDK skipped the parse step.
                parsed: LessonContent | None = getattr(response, "parsed", None)
                if parsed is None:
                    raw = getattr(response, "text", "") or ""
                    if not raw:
                        raise RuntimeError(
                            "generator: empty response from Gemini "
                            "(no .parsed, no .text)"
                        )
                    parsed = LessonContent.model_validate_json(raw)

                # Token-usage log — same shape as services.gemini.
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    log.info(
                        "gemini_usage",
                        op="content_generate",
                        model=self._model,
                        prompt_tokens=getattr(usage, "prompt_token_count", None),
                        output_tokens=getattr(usage, "candidates_token_count", None),
                        total_tokens=getattr(usage, "total_token_count", None),
                    )
                log.info(
                    "content_generate_ok",
                    topic=topic_name,
                    items=len(parsed.items),
                )
                return parsed

        raise RuntimeError("generator: retry loop exhausted")


__all__ = ["LessonGenerator"]
