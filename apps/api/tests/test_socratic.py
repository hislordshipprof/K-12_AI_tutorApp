"""Unit tests for ``SocraticAgent`` + prompt builders.

We mock ``GeminiService.stream_text`` so no network is needed. The asserts
focus on three guarantees:

1. The persona + Socratic rules + session context all reach the model.
2. ``stream_text`` is invoked with ``ARIA_BASE_PERSONA`` in the system slot.
3. Canned reaction responses are returned by ``respond_to_reaction``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.prompts import (
    ARIA_BASE_PERSONA,
    QUESTION_PROMPT,
    REACTION_RESPONSES,
    REPLY_PROMPT,
    SOCRATIC_RULES,
)
from app.agents.socratic import SocraticAgent
from app.agents.state import QATurn, SessionState


# ── helpers ──────────────────────────────────────────────────────────────────
def _make_gemini_mock(chunks: list[str]) -> MagicMock:
    """Build a ``GeminiService`` mock whose ``stream_text`` yields chunks.

    We capture call kwargs so the tests can assert what was sent.
    """
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


# ── prompt builders ──────────────────────────────────────────────────────────
def test_question_prompt_contains_rules_and_context() -> None:
    state = SessionState(topic_id="t1", topic_name="Waves: amplitude", step_idx=2)
    prompt = QUESTION_PROMPT(state, "What is amplitude?")

    assert "TEACHING RULES" in prompt
    assert "NEVER give the final answer" in prompt
    assert "Waves: amplitude" in prompt
    assert "Step index: 2" in prompt
    assert "What is amplitude?" in prompt


def test_question_prompt_includes_recent_history() -> None:
    state = SessionState(topic_id="t1", topic_name="Waves")
    state.qa_history.extend(
        [
            QATurn(question=f"Q{i}", answer=f"A{i}") for i in range(5)
        ]
    )
    prompt = QUESTION_PROMPT(state, "follow-up?")

    # Only the last 3 turns should be present.
    assert "Q2" in prompt and "Q3" in prompt and "Q4" in prompt
    assert "Q0" not in prompt and "Q1" not in prompt


def test_reply_prompt_branches_documented() -> None:
    state = SessionState(topic_id="t1", topic_name="Waves")
    prompt = REPLY_PROMPT(state, "I think amplitude is the height")

    # The prompt encodes the four expected behavioural branches.
    assert "correct formula" in prompt.lower() or "v = f" in prompt
    assert "i don't know" in prompt.lower()
    assert "tell me more" in prompt.lower()
    # The student's actual text appears verbatim.
    assert "I think amplitude is the height" in prompt


def test_socratic_rules_forbid_direct_answer() -> None:
    """Sanity check on the rules string — Aria must not just *define* terms."""
    assert "NEVER give the final answer" in SOCRATIC_RULES
    assert "Ask before telling" in SOCRATIC_RULES


def test_socratic_rules_require_latex_math_formatting() -> None:
    """Aria must emit math in $...$ / $$...$$ so KaTeX can typeset it.

    Without this rule the model defaults to bare ASCII ('T = 1/f') which
    renders as plain text and looks unprofessional in a tutoring app.
    """
    assert "MATH FORMATTING" in SOCRATIC_RULES
    assert "$T = 1/f$" in SOCRATIC_RULES
    assert "$$" in SOCRATIC_RULES
    # The rules MUST forbid bare ASCII to keep the rendering layer
    # consistent across lesson content and Aria's live Q&A replies.
    assert "Do NOT emit bare ASCII math" in SOCRATIC_RULES


# ── streaming methods ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_respond_to_question_streams_and_uses_persona() -> None:
    gemini = _make_gemini_mock(["Hmm", ", ", "what do you think?"])
    agent = SocraticAgent(gemini)
    state = SessionState(topic_id="t1", topic_name="Waves: amplitude")

    out: list[str] = []
    async for tok in agent.respond_to_question(state, "What is amplitude?"):
        out.append(tok)

    assert "".join(out) == "Hmm, what do you think?"
    captured = gemini._captured  # type: ignore[attr-defined]
    # Persona is in the system slot.
    assert captured["system"] == ARIA_BASE_PERSONA
    # Rules + context + question all made it into the user slot.
    assert "TEACHING RULES" in captured["prompt"]
    assert "Waves: amplitude" in captured["prompt"]
    assert "What is amplitude?" in captured["prompt"]


@pytest.mark.asyncio
async def test_respond_to_reply_streams_and_includes_text() -> None:
    gemini = _make_gemini_mock(["Nice ", "try!"])
    agent = SocraticAgent(gemini)
    state = SessionState(topic_id="t1", topic_name="Waves")

    out: list[str] = []
    async for tok in agent.respond_to_reply(state, "I think v = f * lambda"):
        out.append(tok)

    assert "".join(out) == "Nice try!"
    captured = gemini._captured  # type: ignore[attr-defined]
    assert captured["system"] == ARIA_BASE_PERSONA
    assert "I think v = f * lambda" in captured["prompt"]


# ── reactions ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "reaction",
    ["slower", "confused", "got_it", "mind_blown"],
)
def test_respond_to_reaction_returns_canned_text(reaction: str) -> None:
    agent = SocraticAgent(MagicMock())
    state = SessionState(topic_id="t1")
    msg = agent.respond_to_reaction(state, reaction)
    assert msg == REACTION_RESPONSES[reaction]
    assert len(msg) > 10  # non-trivial copy


def test_respond_to_reaction_unknown_falls_back() -> None:
    """Unknown reaction keys should NOT raise — fall back to 'confused' copy."""
    agent = SocraticAgent(MagicMock())
    state = SessionState(topic_id="t1")
    msg = agent.respond_to_reaction(state, "wat")
    assert msg == REACTION_RESPONSES["confused"]
