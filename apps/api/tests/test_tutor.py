"""Unit tests for ``TutorAgent`` orchestration + persistence semantics."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agents.prompts import REACTION_RESPONSES
from app.agents.state import SessionState
from app.agents.tutor import TutorAgent


# ── helpers ──────────────────────────────────────────────────────────────────
def _make_gemini_mock(chunks: list[str]) -> MagicMock:
    """Mock ``GeminiService`` whose ``stream_text`` yields ``chunks``."""

    async def _stream(*, prompt: str, system: str | None = None, model: str | None = None) -> AsyncIterator[str]:
        for c in chunks:
            yield c

    gemini = MagicMock(name="gemini")
    gemini.stream_text = _stream  # type: ignore[assignment]
    return gemini


def _make_supabase_mock(initial_state: dict[str, Any] | None = None) -> MagicMock:
    """Build a supabase-py-shaped mock that records ``update`` calls AND
    persists the last-saved state so subsequent ``select`` calls see it.

    This matches real Supabase semantics: a write is visible to the next
    read. Without that, multi-turn tests would lose state between calls.

    The chain we mimic:
        client.table(t).select(...).eq(...).limit(...).execute() → APIResponse(data=[...])
        client.table(t).update(...).eq(...).execute() → APIResponse
    """
    captured: dict[str, Any] = {
        "updates": [],
        "current_state": initial_state if initial_state is not None else None,
    }

    def _select_execute() -> MagicMock:
        resp = MagicMock()
        if captured["current_state"] is None:
            resp.data = []
        else:
            resp.data = [
                {
                    "id": "sid",
                    "topic_id": "topic-x",
                    "agent_state": captured["current_state"],
                }
            ]
        return resp

    # Builder chain returned from .table(...).select(...)
    select_chain = MagicMock()
    select_chain.eq.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.side_effect = _select_execute

    # Builder chain returned from .table(...).update(...)
    update_chain = MagicMock()
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = MagicMock(data=[{"id": "sid"}])

    def _capture_update(payload: dict[str, Any]) -> MagicMock:
        captured["updates"].append(payload)
        if "agent_state" in payload:
            captured["current_state"] = payload["agent_state"]
        return update_chain

    table_mock = MagicMock()
    table_mock.select.return_value = select_chain
    table_mock.update.side_effect = _capture_update

    client = MagicMock(name="supabase")
    client.table.return_value = table_mock
    client._captured = captured  # type: ignore[attr-defined]
    return client


# ── state load / save ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_or_init_state_falls_back_to_memory_when_no_supabase(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No Supabase client → initialise fresh state, log a notice."""
    agent = TutorAgent(_make_gemini_mock([]), supabase=None)
    state = await agent.get_or_init_state("sid-1", user_id="u1", topic_id="topic-x")
    assert isinstance(state, SessionState)
    assert state.topic_id == "topic-x"
    assert state.qa_history == []

    # Same session_id returns the cached instance.
    state2 = await agent.get_or_init_state("sid-1", user_id="u1")
    assert state2 is state


@pytest.mark.asyncio
async def test_get_or_init_state_supabase_failure_is_silent() -> None:
    """A Supabase exception should NOT bubble up — fall back gracefully."""
    bad_supabase = MagicMock()
    bad_supabase.table.side_effect = RuntimeError("network blew up")
    agent = TutorAgent(_make_gemini_mock([]), supabase=bad_supabase)

    state = await agent.get_or_init_state("sid-x", user_id="u1", topic_id="t9")
    assert isinstance(state, SessionState)
    assert state.topic_id == "t9"


@pytest.mark.asyncio
async def test_get_or_init_state_reads_existing_supabase_row() -> None:
    """When Supabase returns a stored state, we should hydrate from it."""
    stored = {
        "topic_id": "topic-x",
        "topic_name": "Waves",
        "step_idx": 4,
        "qa_history": [
            {"question": "What is a wave?", "answer": "Great q…", "source": "text"}
        ],
        "student_signals": {"last_reaction": "got_it"},
    }
    supa = _make_supabase_mock(initial_state=stored)
    agent = TutorAgent(_make_gemini_mock([]), supabase=supa)

    state = await agent.get_or_init_state("sid-2", user_id="u1")
    assert state.step_idx == 4
    assert state.topic_name == "Waves"
    assert len(state.qa_history) == 1
    assert state.qa_history[0].question == "What is a wave?"
    assert state.student_signals.get("last_reaction") == "got_it"


@pytest.mark.asyncio
async def test_save_state_writes_to_supabase() -> None:
    supa = _make_supabase_mock(initial_state={})
    agent = TutorAgent(_make_gemini_mock([]), supabase=supa)
    state = SessionState(topic_id="t1", topic_name="Waves", step_idx=1)
    await agent.save_state("sid-3", state)

    updates = supa._captured["updates"]  # type: ignore[attr-defined]
    assert len(updates) == 1
    payload = updates[0]
    assert "agent_state" in payload
    saved = payload["agent_state"]
    assert saved["topic_id"] == "t1"
    assert saved["topic_name"] == "Waves"


@pytest.mark.asyncio
async def test_save_state_silent_on_supabase_failure() -> None:
    bad = MagicMock()
    bad.table.side_effect = RuntimeError("boom")
    agent = TutorAgent(_make_gemini_mock([]), supabase=bad)
    state = SessionState(topic_id="t1")
    # Must not raise.
    await agent.save_state("sid-4", state)
    # And still caches locally as a safety net.
    assert agent._memory["sid-4"] is state


# ── handle_question ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_handle_question_yields_tokens_and_saves_state() -> None:
    supa = _make_supabase_mock(initial_state={})
    gemini = _make_gemini_mock(["What ", "do ", "you ", "think?"])
    agent = TutorAgent(gemini, supabase=supa)

    pieces: list[str] = []
    async for tok in agent.handle_question(
        "sid-q",
        user_id="u1",
        question="What is amplitude?",
        source="text",
        topic_id="topic-waves",
    ):
        pieces.append(tok)

    assert "".join(pieces) == "What do you think?"

    # State write recorded.
    updates = supa._captured["updates"]  # type: ignore[attr-defined]
    assert len(updates) == 1
    saved = updates[0]["agent_state"]
    history = saved.get("qa_history") or []
    assert len(history) == 1
    assert history[0]["question"] == "What is amplitude?"
    assert history[0]["answer"] == "What do you think?"
    assert history[0]["source"] == "text"


@pytest.mark.asyncio
async def test_handle_question_appends_to_existing_history() -> None:
    """Second question should land *after* the first in qa_history."""
    supa = _make_supabase_mock(initial_state={})
    gemini = _make_gemini_mock(["ok"])
    agent = TutorAgent(gemini, supabase=supa)

    async for _ in agent.handle_question("sid-h", "u1", "q1", topic_id="t"):
        pass
    async for _ in agent.handle_question("sid-h", "u1", "q2", topic_id="t"):
        pass

    updates = supa._captured["updates"]  # type: ignore[attr-defined]
    last = updates[-1]["agent_state"]
    history = last["qa_history"]
    assert [t["question"] for t in history] == ["q1", "q2"]


# ── handle_reply ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_handle_reply_streams_and_persists() -> None:
    supa = _make_supabase_mock(initial_state={})
    gemini = _make_gemini_mock(["Cool ", "— ", "why?"])
    agent = TutorAgent(gemini, supabase=supa)

    out: list[str] = []
    async for tok in agent.handle_reply(
        "sid-r", "u1", "I think v = f * lambda", topic_id="t"
    ):
        out.append(tok)
    assert "".join(out) == "Cool — why?"

    updates = supa._captured["updates"]  # type: ignore[attr-defined]
    saved = updates[-1]["agent_state"]
    history = saved["qa_history"]
    assert len(history) == 1
    # We tag replies with a synthetic Q label so the transcript stays readable.
    assert "student said" in history[0]["question"].lower()
    assert history[0]["answer"] == "Cool — why?"


# ── handle_reaction ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reaction",
    ["slower", "confused", "got_it", "mind_blown"],
)
async def test_handle_reaction_returns_canned_response(reaction: str) -> None:
    supa = _make_supabase_mock(initial_state={})
    agent = TutorAgent(_make_gemini_mock([]), supabase=supa)
    msg = await agent.handle_reaction(
        "sid-react", user_id="u1", reaction=reaction, topic_id="t"
    )
    assert msg == REACTION_RESPONSES[reaction]


@pytest.mark.asyncio
async def test_handle_reaction_updates_signals() -> None:
    supa = _make_supabase_mock(initial_state={})
    agent = TutorAgent(_make_gemini_mock([]), supabase=supa)

    await agent.handle_reaction("sid-s", "u1", "confused", topic_id="t")
    await agent.handle_reaction("sid-s", "u1", "slower", topic_id="t")

    state = agent._memory["sid-s"]
    assert state.student_signals.get("last_reaction") == "slower"
    # 'confused' bumps confusion by 2, 'slower' by another 1, capped at 3.
    assert state.student_signals.get("confusion_level") == 3
    # And hint_level grows with negative reactions (capped at 3).
    assert state.hint_level >= 2


@pytest.mark.asyncio
async def test_handle_reaction_positive_reduces_confusion() -> None:
    supa = _make_supabase_mock(initial_state={})
    agent = TutorAgent(_make_gemini_mock([]), supabase=supa)

    await agent.handle_reaction("sid-p", "u1", "confused", topic_id="t")
    await agent.handle_reaction("sid-p", "u1", "got_it", topic_id="t")
    state = agent._memory["sid-p"]
    assert state.student_signals.get("confusion_level") == 1
