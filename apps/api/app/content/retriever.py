"""Runtime RAG retriever — surfaces the lesson chunks Aria just covered.

Called by ``TutorAgent.handle_question`` / ``handle_reply``. The flow:

  1. Embed the student's question with ``gemini-embedding-2`` (768-d).
  2. Call the Supabase RPC ``match_lesson_chunks`` to cosine-search
     ``lesson_embeddings`` within the current topic.
  3. Augment the top-k matches with the chunk(s) whose ``ordinal`` sits at
     ``last_step_idx`` and ``last_step_idx ± 1`` — guarantees temporal
     grounding even when cosine misses (e.g. a "wait, what?" question).
  4. Return a deduped list of ``RetrievedChunk`` records, ranked: temporal
     anchors first (they're definitionally relevant), then cosine matches.

Failure-tolerant: ANY error (no Supabase, missing RPC, embedder blow-up)
logs a warning and returns ``[]``. The caller falls back to the existing
non-RAG prompt path so the tutor never breaks because retrieval failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.content.embedder import get_embedder
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class RetrievedChunk:
    """One lesson chunk surfaced to the tutor at request time.

    Mirrors the shape of ``app.content.chunker.Chunk`` (minus equations /
    terms which aren't needed for the Socratic prompt) so the same
    ``RAG_QUESTION_PROMPT`` formatter handles both call sites.
    """

    chunk_id: str
    ordinal: int
    text: str
    source_url: str
    similarity: float

    # ``RAG_QUESTION_PROMPT._format_rag_chunks`` only reads ``.text`` and
    # ``.ordinal``; keeping the same attribute names means we can hand
    # ``RetrievedChunk`` instances straight to the prompt builder.


def _serialise_vector(vec: list[float]) -> str:
    """Format a 768-d vector for the pgvector RPC param (``[v1,v2,...]``)."""
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"


def _supabase() -> Any | None:
    """Return the admin Supabase client, or ``None`` if not configured."""
    try:
        from app.core.supabase import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("rag_supabase_unavailable", error=str(e))
        return None


def _row_to_chunk(row: dict[str, Any]) -> RetrievedChunk | None:
    """Convert a Supabase row to ``RetrievedChunk``; skip malformed rows."""
    try:
        return RetrievedChunk(
            chunk_id=str(row.get("chunk_id") or ""),
            ordinal=int(row.get("ordinal") or 0),
            text=str(row.get("text") or ""),
            source_url=str(row.get("source_url") or ""),
            similarity=float(row.get("similarity") or 0.0),
        )
    except (TypeError, ValueError):
        return None


async def fetch_context(
    topic_id: str | UUID,
    question: str,
    last_step_idx: int | None = None,
    k: int = 3,
    threshold: float = 0.6,
    *,
    supabase: Any | None = None,
    embedder: Any | None = None,
) -> list[RetrievedChunk]:
    """Retrieve the lesson chunks Aria should anchor her reply on.

    Args:
        topic_id: Current topic in the session. Empty string / ``None`` →
            return ``[]`` (we can't search without a topic).
        question: The student's question; embedded for cosine search.
        last_step_idx: Where the lesson currently sits — used to also pull
            ``ordinal in {idx-1, idx, idx+1}`` for temporal grounding.
        k: Top-k cosine matches to request (default 3).
        threshold: Minimum cosine similarity for a match to count (0.0–1.0).
        supabase / embedder: Test seams — production callers omit both.

    Returns:
        Deduped list of ``RetrievedChunk``. Temporal anchors appear first,
        followed by cosine matches in similarity order. Empty list on any
        error (logged), so the caller can fall back gracefully.
    """
    if not topic_id or not str(topic_id).strip():
        return []
    if not question or not question.strip():
        return []

    topic_id_str = str(topic_id)

    sb = supabase if supabase is not None else _supabase()
    if sb is None:
        log.info("rag_skip_no_supabase", topic_id=topic_id_str)
        return []

    emb = embedder if embedder is not None else get_embedder()

    # 1. Embed the question.
    try:
        query_vec = await emb.embed_query(question)
    except Exception as e:  # noqa: BLE001
        log.warning("rag_embed_failed", topic_id=topic_id_str, error=str(e))
        return []
    if not query_vec:
        log.warning("rag_embed_empty", topic_id=topic_id_str)
        return []

    # 2. Cosine search via RPC.
    cosine_chunks: list[RetrievedChunk] = []
    try:
        resp = sb.rpc(
            "match_lesson_chunks",
            {
                "p_topic_id": topic_id_str,
                "p_query_embedding": _serialise_vector(query_vec),
                "p_match_count": int(k),
                "p_threshold": float(threshold),
            },
        ).execute()
        rows = getattr(resp, "data", None) or []
        for row in rows:
            c = _row_to_chunk(row)
            if c is not None:
                cosine_chunks.append(c)
    except Exception as e:  # noqa: BLE001
        # Don't bail — we may still recover the temporal anchors below.
        log.warning("rag_rpc_failed", topic_id=topic_id_str, error=str(e))

    # 3. Temporal anchors — chunk(s) at ordinal ± 1.
    temporal_chunks: list[RetrievedChunk] = []
    if last_step_idx is not None:
        wanted = sorted(
            {idx for idx in (last_step_idx - 1, last_step_idx, last_step_idx + 1) if idx >= 0}
        )
        if wanted:
            try:
                resp = (
                    sb.table("lesson_embeddings")
                    .select("chunk_id, ordinal, text, source_url")
                    .eq("topic_id", topic_id_str)
                    .in_("ordinal", wanted)
                    .execute()
                )
                rows = getattr(resp, "data", None) or []
                for row in rows:
                    # Temporal chunks come from a non-RPC table read, so they
                    # have no similarity score — stamp a sentinel value of
                    # 1.0 to signal "definitionally relevant".
                    enriched = {**row, "similarity": 1.0}
                    c = _row_to_chunk(enriched)
                    if c is not None:
                        temporal_chunks.append(c)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "rag_temporal_fetch_failed",
                    topic_id=topic_id_str,
                    error=str(e),
                )

    # 4. Dedupe — prefer temporal anchors first, then cosine matches by
    #    similarity descending.
    seen: set[str] = set()
    merged: list[RetrievedChunk] = []
    for c in temporal_chunks:
        key = c.chunk_id or f"ord-{c.ordinal}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)

    for c in sorted(cosine_chunks, key=lambda x: x.similarity, reverse=True):
        key = c.chunk_id or f"ord-{c.ordinal}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)

    log.info(
        "rag_fetch_context",
        topic_id=topic_id_str,
        question_len=len(question),
        last_step_idx=last_step_idx,
        n_temporal=len(temporal_chunks),
        n_cosine=len(cosine_chunks),
        n_returned=len(merged),
    )
    return merged


__all__ = ["RetrievedChunk", "fetch_context"]
