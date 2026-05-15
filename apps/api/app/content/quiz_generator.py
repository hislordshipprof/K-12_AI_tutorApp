"""Structured-output quiz generator (Q2).

Calls ``gemini-pro-latest`` with ``response_schema=QuizSet`` so the model
output lands as a typed Pydantic object. Mirrors the shape of
``content.generator.LessonGenerator`` so the two stay easy to compare.
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
from app.content.quiz_prompts import (
    QUIZ_GENERATION_SYSTEM_PROMPT,
    QUIZ_GENERATION_USER_PROMPT,
)
from app.content.quiz_schema import QuizSet
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


class QuizGenerator:
    """Async wrapper around ``gemini-pro-latest`` for 3-question quiz sets."""

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
            self._gemini = GeminiService()
        return self._gemini

    async def generate(
        self,
        topic_name: str,
        lesson: LessonContent | None,
        source_chunks: list[Chunk],
        *,
        extra_instructions: str | None = None,
        temperature: float = 0.7,
    ) -> QuizSet:
        """Produce one 3-question ``QuizSet`` for ``topic_name``."""
        user_prompt = QUIZ_GENERATION_USER_PROMPT(
            topic_name=topic_name,
            lesson=lesson,
            source_chunks=source_chunks,
            extra_instructions=extra_instructions,
        )

        client = self.gemini.client

        config: dict[str, Any] = {
            "system_instruction": QUIZ_GENERATION_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": QuizSet,
            "temperature": temperature,
        }

        log.info(
            "quiz_generate_start",
            model=self._model,
            topic=topic_name,
            chunks_n=len(source_chunks),
            has_lesson=lesson is not None,
        )

        async for attempt in _retry_policy():
            with attempt:
                response = await client.aio.models.generate_content(
                    model=self._model,
                    contents=user_prompt,
                    config=config,
                )
                parsed: QuizSet | None = getattr(response, "parsed", None)
                if parsed is None:
                    raw = getattr(response, "text", "") or ""
                    if not raw:
                        raise RuntimeError(
                            "quiz generator: empty response from Gemini"
                        )
                    parsed = QuizSet.model_validate_json(raw)

                usage = getattr(response, "usage_metadata", None)
                if usage:
                    log.info(
                        "gemini_usage",
                        op="quiz_generate",
                        model=self._model,
                        prompt_tokens=getattr(usage, "prompt_token_count", None),
                        output_tokens=getattr(usage, "candidates_token_count", None),
                        total_tokens=getattr(usage, "total_token_count", None),
                    )
                log.info(
                    "quiz_generate_ok",
                    topic=topic_name,
                    items=len(parsed.items),
                )
                return parsed

        raise RuntimeError("quiz generator: retry loop exhausted")


__all__ = ["QuizGenerator"]
