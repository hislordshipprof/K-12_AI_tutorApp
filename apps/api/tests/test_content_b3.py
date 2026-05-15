"""Tests for the B3 runtime RAG layer.

Two surfaces under test:

  • ``app.content.retriever.fetch_context`` — embed → cosine-RPC →
    temporal-anchor → dedupe. Embedder + Supabase are mocked.
  • ``SocraticAgent.respond_to_*`` with the optional ``retrieved_chunks``
    arg — must route the prompt through ``RAG_QUESTION_PROMPT`` when
    chunks are present and fall back to the legacy ``QUESTION_PROMPT`` /
    ``REPLY_PROMPT`` path when they aren't.

All tests run offline — no real Gemini or Supabase calls.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

# Match conftest env wiring (file may be invoked in isolation).
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("DEV_MODE", "true")

from app.agents.prompts import ARIA_BASE_PERSONA  # noqa: E402
from app.agents.socratic import SocraticAgent  # noqa: E402
from app.agents.state import SessionState  # noqa: E402
from app.agents.tutor import TutorAgent  # noqa: E402
from app.content import retriever as rag_retriever  # noqa: E402
from app.content.retriever import RetrievedChunk, fetch_context  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
class _FakeEmbedder:
    """Mock embedder — returns a fixed 768-d vector for ``embed_query``."""

    def __init__(self, vec: list[float] | None = None) -> None:
        self._vec = vec or [0.5] * 768

    async def embed_query(self, text: str) -> list[float]:
        return list(self._vec)


def _make_rpc_supabase(
    cosine_rows: list[dict[str, Any]] | None = None,
    temporal_rows: list[dict[str, Any]] | None = None,
    *,
    rpc_raises: BaseException | None = None,
) -> MagicMock:
    """Supabase mock with both ``.rpc(...)`` (cosine) and ``.table(...).select(...).in_()``
    (temporal anchors) wired up."""

    cosine_rows = cosine_rows or []
    temporal_rows = temporal_rows or []
    captured: dict[str, Any] = {"rpc_calls": [], "select_calls": []}

    # ── .rpc("match_lesson_chunks", {...}).execute() ────────────────────────
    rpc_chain = MagicMock()

    def _rpc_execute() -> MagicMock:
        if rpc_raises is not None:
            raise rpc_raises
        resp = MagicMock()
        resp.data = list(cosine_rows)
        return resp

    rpc_chain.execute.side_effect = _rpc_execute

    def _rpc(fn_name: str, payload: dict[str, Any]) -> MagicMock:
        captured["rpc_calls"].append({"fn": fn_name, "payload": payload})
        return rpc_chain

    # ── .table("lesson_embeddings").select(...).eq(...).in_(...).execute() ──
    table_chain = MagicMock()
    table_chain.select.return_value = table_chain
    table_chain.eq.return_value = table_chain

    def _in_(col: str, values: list[Any]) -> MagicMock:
        captured["select_calls"].append({"col": col, "values": list(values)})
        return table_chain

    table_chain.in_.side_effect = _in_
    table_chain.execute.return_value = MagicMock(data=list(temporal_rows))

    sb = MagicMock(name="supabase-rag")
    sb.rpc.side_effect = _rpc
    sb.table.return_value = table_chain
    sb._captured = captured  # type: ignore[attr-defined]
    return sb


def _make_gemini_mock(chunks: list[str]) -> MagicMock:
    """Mock ``GeminiService.stream_text`` — yields ``chunks`` and captures kwargs."""
    captured: dict[str, Any] = {}

    async def _stream(
        *, prompt: str, system: str | None = None, model: str | None = None
    ) -> AsyncIterator[str]:
        captured["prompt"] = prompt
        captured["system"] = system
        captured["model"] = model
        for c in chunks:
            yield c

    gemini = MagicMock(name="gemini")
    gemini.stream_text = _stream  # type: ignore[assignment]
    gemini._captured = captured  # type: ignore[attr-defined]
    return gemini


# ─────────────────────────────────────────────────────────────────────────────
# retriever.fetch_context
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_fetch_context_empty_topic_returns_empty() -> None:
    """No topic → no retrieval, no errors."""
    sb = _make_rpc_supabase()
    out = await fetch_context(
        topic_id="",
        question="why does a stiffer spring oscillate faster?",
        supabase=sb,
        embedder=_FakeEmbedder(),
    )
    assert out == []
    # RPC must NOT be called when there's nothing to scope to.
    assert sb._captured["rpc_calls"] == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_fetch_context_empty_question_returns_empty() -> None:
    sb = _make_rpc_supabase()
    out = await fetch_context(
        topic_id="topic-osc",
        question="   ",
        supabase=sb,
        embedder=_FakeEmbedder(),
    )
    assert out == []


@pytest.mark.asyncio
async def test_fetch_context_returns_cosine_rows_in_similarity_order() -> None:
    cosine_rows = [
        {
            "chunk_id": "c1",
            "ordinal": 5,
            "text": "Hooke's law: F = -k x. A stiffer spring has larger k.",
            "source_url": "https://openstax.org/.../16-1-...",
            "similarity": 0.92,
        },
        {
            "chunk_id": "c2",
            "ordinal": 7,
            "text": "Period: T = 2π√(m/k). Larger k → smaller T.",
            "source_url": "https://openstax.org/.../16-3-...",
            "similarity": 0.87,
        },
    ]
    sb = _make_rpc_supabase(cosine_rows=cosine_rows)
    out = await fetch_context(
        topic_id="topic-osc",
        question="why does a stiffer spring oscillate faster?",
        last_step_idx=None,
        k=3,
        threshold=0.6,
        supabase=sb,
        embedder=_FakeEmbedder(),
    )
    assert [c.chunk_id for c in out] == ["c1", "c2"]
    assert all(isinstance(c, RetrievedChunk) for c in out)
    # RPC was called once with the right shape.
    calls = sb._captured["rpc_calls"]  # type: ignore[attr-defined]
    assert len(calls) == 1
    assert calls[0]["fn"] == "match_lesson_chunks"
    payload = calls[0]["payload"]
    assert payload["p_topic_id"] == "topic-osc"
    assert payload["p_match_count"] == 3
    assert payload["p_threshold"] == 0.6
    # pgvector requires the embedding as a string-formatted vector literal.
    assert payload["p_query_embedding"].startswith("[")
    assert payload["p_query_embedding"].endswith("]")


@pytest.mark.asyncio
async def test_fetch_context_adds_temporal_anchors_when_step_idx_given() -> None:
    """When ``last_step_idx`` is set, we also pull ordinal ± 1 from the table."""
    cosine_rows = [
        {
            "chunk_id": "c-far",
            "ordinal": 0,
            "text": "early intro paragraph",
            "source_url": "u1",
            "similarity": 0.81,
        }
    ]
    temporal_rows = [
        {
            "chunk_id": "c-cur",
            "ordinal": 5,
            "text": "current chunk",
            "source_url": "u2",
        },
        {
            "chunk_id": "c-next",
            "ordinal": 6,
            "text": "next chunk",
            "source_url": "u3",
        },
    ]
    sb = _make_rpc_supabase(cosine_rows=cosine_rows, temporal_rows=temporal_rows)
    out = await fetch_context(
        topic_id="topic-osc",
        question="quick recap?",
        last_step_idx=5,
        supabase=sb,
        embedder=_FakeEmbedder(),
    )
    # Temporal anchors come FIRST (definitionally relevant), then cosine.
    assert [c.chunk_id for c in out] == ["c-cur", "c-next", "c-far"]
    selects = sb._captured["select_calls"]  # type: ignore[attr-defined]
    assert selects and selects[0]["col"] == "ordinal"
    # Asked for {4, 5, 6} (idx - 1, idx, idx + 1).
    assert sorted(selects[0]["values"]) == [4, 5, 6]


@pytest.mark.asyncio
async def test_fetch_context_dedupes_temporal_and_cosine() -> None:
    """If the same chunk_id appears in both the temporal and cosine sets,
    we keep one copy (the temporal one — it has the canonical score=1.0)."""
    cosine_rows = [
        {
            "chunk_id": "c5",
            "ordinal": 5,
            "text": "match",
            "source_url": "u",
            "similarity": 0.9,
        }
    ]
    temporal_rows = [
        {
            "chunk_id": "c5",
            "ordinal": 5,
            "text": "match",
            "source_url": "u",
        }
    ]
    sb = _make_rpc_supabase(cosine_rows=cosine_rows, temporal_rows=temporal_rows)
    out = await fetch_context(
        topic_id="topic-osc",
        question="…",
        last_step_idx=5,
        supabase=sb,
        embedder=_FakeEmbedder(),
    )
    assert len(out) == 1
    # Temporal won — sentinel similarity 1.0.
    assert out[0].chunk_id == "c5"
    assert out[0].similarity == 1.0


@pytest.mark.asyncio
async def test_fetch_context_swallows_rpc_failure() -> None:
    """A broken RPC must not break retrieval — log + return []."""
    sb = _make_rpc_supabase(rpc_raises=RuntimeError("rpc kaboom"))
    out = await fetch_context(
        topic_id="topic-osc",
        question="why?",
        last_step_idx=None,
        supabase=sb,
        embedder=_FakeEmbedder(),
    )
    assert out == []


@pytest.mark.asyncio
async def test_fetch_context_falls_back_to_temporal_when_rpc_dies() -> None:
    """Even if cosine search fails, temporal anchors still surface."""
    temporal_rows = [
        {
            "chunk_id": "c-cur",
            "ordinal": 4,
            "text": "current",
            "source_url": "u",
        }
    ]
    sb = _make_rpc_supabase(
        rpc_raises=RuntimeError("rpc kaboom"),
        temporal_rows=temporal_rows,
    )
    out = await fetch_context(
        topic_id="topic-osc",
        question="why?",
        last_step_idx=4,
        supabase=sb,
        embedder=_FakeEmbedder(),
    )
    assert [c.chunk_id for c in out] == ["c-cur"]


@pytest.mark.asyncio
async def test_fetch_context_swallows_embedder_failure() -> None:
    class _BrokenEmbedder:
        async def embed_query(self, _text: str) -> list[float]:
            raise RuntimeError("embedder kaboom")

    sb = _make_rpc_supabase()
    out = await fetch_context(
        topic_id="topic-osc",
        question="why?",
        supabase=sb,
        embedder=_BrokenEmbedder(),
    )
    assert out == []
    # If the embedder fails we should NEVER have made an RPC call.
    assert sb._captured["rpc_calls"] == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_fetch_context_no_supabase_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Supabase client available (and none injected) → graceful []."""
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: None)
    out = await fetch_context(
        topic_id="topic-osc",
        question="why?",
        embedder=_FakeEmbedder(),
    )
    assert out == []


# ─────────────────────────────────────────────────────────────────────────────
# SocraticAgent — RAG-aware prompt selection
# ─────────────────────────────────────────────────────────────────────────────
def _make_chunk(text: str, ordinal: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{ordinal}",
        ordinal=ordinal,
        text=text,
        source_url="https://example.test/x",
        similarity=0.9,
    )


@pytest.mark.asyncio
async def test_respond_to_question_uses_rag_prompt_when_chunks_present() -> None:
    """With chunks, the RAG prompt must include literal source text."""
    gemini = _make_gemini_mock(["Hmm…"])
    agent = SocraticAgent(gemini)
    state = SessionState(topic_id="t1", topic_name="Oscillations", step_idx=3)

    chunks = [
        _make_chunk("A stiffer spring has a larger k constant.", ordinal=2),
        _make_chunk("Period T = 2π√(m/k); larger k → smaller T.", ordinal=3),
    ]

    out: list[str] = []
    async for tok in agent.respond_to_question(
        state,
        "why does a stiffer spring oscillate faster?",
        retrieved_chunks=chunks,
    ):
        out.append(tok)

    assert "".join(out) == "Hmm…"
    captured = gemini._captured  # type: ignore[attr-defined]
    # Persona stays in system.
    assert captured["system"] == ARIA_BASE_PERSONA
    # RAG marker phrases land in the user prompt.
    assert "SOURCE PASSAGES" in captured["prompt"]
    # The literal chunk text appears (paraphrased framing is enforced by
    # prompt copy, but the model needs the source to paraphrase).
    assert "stiffer spring" in captured["prompt"]
    assert "2π√(m/k)" in captured["prompt"]
    # The student's question still appears.
    assert "why does a stiffer spring oscillate faster?" in captured["prompt"]


@pytest.mark.asyncio
async def test_respond_to_question_falls_back_to_legacy_prompt_when_no_chunks() -> None:
    """No chunks → existing ``QUESTION_PROMPT`` path (graceful fallback)."""
    gemini = _make_gemini_mock(["ok"])
    agent = SocraticAgent(gemini)
    state = SessionState(topic_id="t1", topic_name="Oscillations", step_idx=3)

    async for _ in agent.respond_to_question(
        state, "what is amplitude?", retrieved_chunks=None
    ):
        pass

    captured = gemini._captured  # type: ignore[attr-defined]
    # Legacy prompt marker is "TEACHING RULES" header — present in BOTH the
    # legacy and RAG prompt (SOCRATIC_RULES is shared). The unique fingerprint
    # of the legacy path is the absence of "SOURCE PASSAGES".
    assert "SOURCE PASSAGES" not in captured["prompt"]
    assert "what is amplitude?" in captured["prompt"]


@pytest.mark.asyncio
async def test_respond_to_question_empty_chunks_list_is_fallback() -> None:
    """``retrieved_chunks=[]`` should be treated as no-chunks → legacy path."""
    gemini = _make_gemini_mock(["ok"])
    agent = SocraticAgent(gemini)
    state = SessionState(topic_id="t1", topic_name="Oscillations")
    async for _ in agent.respond_to_question(state, "q?", retrieved_chunks=[]):
        pass
    captured = gemini._captured  # type: ignore[attr-defined]
    assert "SOURCE PASSAGES" not in captured["prompt"]


@pytest.mark.asyncio
async def test_respond_to_reply_uses_rag_prompt_when_chunks_present() -> None:
    """Reply path also benefits from RAG grounding."""
    gemini = _make_gemini_mock(["Cool!"])
    agent = SocraticAgent(gemini)
    state = SessionState(topic_id="t1", topic_name="Oscillations")
    chunks = [_make_chunk("Hooke's law: F = -k x")]

    async for _ in agent.respond_to_reply(
        state, "I think T gets smaller", retrieved_chunks=chunks
    ):
        pass
    captured = gemini._captured  # type: ignore[attr-defined]
    assert "SOURCE PASSAGES" in captured["prompt"]
    assert "Hooke" in captured["prompt"]
    assert "I think T gets smaller" in captured["prompt"]


# ─────────────────────────────────────────────────────────────────────────────
# TutorAgent — end-to-end wiring (retriever → socratic)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tutor_handle_question_threads_retrieved_chunks_into_socratic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: tutor calls retriever, then forwards chunks to socratic."""
    gemini = _make_gemini_mock(["…"])
    agent = TutorAgent(gemini, supabase=None)

    captured_chunks: dict[str, Any] = {}
    real_respond = agent.socratic.respond_to_question

    async def _wrapped_respond(
        state: SessionState,
        question: str,
        retrieved_chunks: list[Any] | None = None,
    ) -> AsyncIterator[str]:
        captured_chunks["passed"] = retrieved_chunks
        async for tok in real_respond(
            state, question, retrieved_chunks=retrieved_chunks
        ):
            yield tok

    agent.socratic.respond_to_question = _wrapped_respond  # type: ignore[assignment]

    # Stub fetch_context to inject a fake chunk.
    fake_chunks = [_make_chunk("anchored passage about amplitude", ordinal=1)]

    async def _fake_fetch(*_a: Any, **_kw: Any) -> list[RetrievedChunk]:
        return list(fake_chunks)

    monkeypatch.setattr(rag_retriever, "fetch_context", _fake_fetch)

    async for _ in agent.handle_question(
        "sid-z", "u1", "what is amplitude?", topic_id="topic-osc"
    ):
        pass

    assert captured_chunks["passed"] is not None
    assert len(captured_chunks["passed"]) == 1
    assert captured_chunks["passed"][0].text == "anchored passage about amplitude"
    # Underlying Gemini prompt was the RAG variant.
    assert "SOURCE PASSAGES" in gemini._captured["prompt"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_tutor_handle_question_swallows_retriever_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the retriever blows up, the tutor must still stream a response."""
    gemini = _make_gemini_mock(["nope, let's try a small step.", " what's your guess?"])
    agent = TutorAgent(gemini, supabase=None)

    async def _broken_fetch(*_a: Any, **_kw: Any) -> list[RetrievedChunk]:
        raise RuntimeError("retriever kaboom")

    monkeypatch.setattr(rag_retriever, "fetch_context", _broken_fetch)

    out: list[str] = []
    async for tok in agent.handle_question(
        "sid-broken", "u1", "what is amplitude?", topic_id="topic-osc"
    ):
        out.append(tok)
    assert "".join(out).startswith("nope")
    # Fallback path → legacy prompt, no source-passage block.
    assert "SOURCE PASSAGES" not in gemini._captured["prompt"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_tutor_handle_question_skips_retrieval_when_no_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No topic_id → the tutor must not even attempt retrieval."""
    gemini = _make_gemini_mock(["ok"])
    agent = TutorAgent(gemini, supabase=None)

    calls: list[tuple[Any, ...]] = []

    async def _spy_fetch(*a: Any, **kw: Any) -> list[RetrievedChunk]:
        calls.append((a, kw))
        return []

    monkeypatch.setattr(rag_retriever, "fetch_context", _spy_fetch)

    async for _ in agent.handle_question("sid-no-topic", "u1", "q?", topic_id=""):
        pass

    assert calls == []  # retrieval was bypassed entirely
