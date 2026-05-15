"""Batch wrapper around `gemini-embedding-2` for content chunks.

768-d output matches the `vector(768)` column in `lesson_embeddings`. We batch
up to ~96 chunks per API call (the Gemini API caps batches; 96 is comfortably
under the documented ceiling for embed-content and matches our chunk volume
per topic).

Retried via tenacity using the same heuristic as `services.gemini`.
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
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

EMBED_DIM = 768
BATCH_SIZE = 96

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


class GeminiEmbedder:
    """Async embeddings client. Lazy genai.Client init so unit tests don't
    require GEMINI_API_KEY."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key or settings.gemini_api_key.get_secret_value()
        self._model = model or settings.gemini_model_embed
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from google import genai

            if not self._api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY is not set — refusing to instantiate embedder."
                )
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed an arbitrary list of texts; batched, retried."""
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            out.extend(await self._embed_batch(batch))
        return out

    async def embed_chunks(self, chunks: list[Chunk]) -> list[list[float]]:
        """Embed each chunk's text. 1:1 ordering with the input list."""
        return await self.embed_texts([c.text for c in chunks])

    async def embed_query(self, text: str) -> list[float]:
        """Single-query embed — runtime RAG entry point (B3)."""
        result = await self.embed_texts([text])
        return result[0] if result else []

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        # The google-genai SDK conflates a `list[str]` into a single Content's
        # parts, which collapses to one embedding regardless of input count.
        # Wrapping each text in its own Content forces one embedding per item.
        contents = [{"parts": [{"text": t}]} for t in batch]
        async for attempt in _retry_policy():
            with attempt:
                response = await self.client.aio.models.embed_content(
                    model=self._model,
                    contents=contents,
                    config={"output_dimensionality": EMBED_DIM},
                )
                embeddings = getattr(response, "embeddings", None) or []
                vecs = [list(getattr(e, "values", e)) for e in embeddings]
                if len(vecs) != len(batch):
                    raise RuntimeError(
                        f"embedder: expected {len(batch)} vectors, got {len(vecs)}"
                    )
                log.info(
                    "content_embed_batch",
                    model=self._model,
                    n=len(batch),
                    dim=EMBED_DIM,
                )
                return vecs
        raise RuntimeError("embedder: retry loop exhausted")


_singleton: GeminiEmbedder | None = None


def get_embedder() -> GeminiEmbedder:
    """Cached `GeminiEmbedder` instance."""
    global _singleton
    if _singleton is None:
        _singleton = GeminiEmbedder()
    return _singleton
