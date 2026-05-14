"""``SocraticAgent`` — the LLM call layer.

This class is intentionally thin: it knows *how* to build a Socratic prompt
and stream the response. It does NOT know about Supabase, sessions, or
persistence — those belong to ``TutorAgent``.

Keeping the layers separate makes it trivial to unit-test the prompt
plumbing by mocking ``GeminiService.stream_text``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from app.agents.prompts import (
    ARIA_BASE_PERSONA,
    QUESTION_PROMPT,
    REACTION_RESPONSES,
    REPLY_PROMPT,
)
from app.agents.state import SessionState
from app.core.logging import get_logger
from app.services.gemini import GeminiService

log = get_logger(__name__)


class SocraticAgent:
    """Generates Aria's Socratic replies via the Gemini text model."""

    def __init__(self, gemini: GeminiService) -> None:
        self.gemini = gemini

    # ---- streaming endpoints --------------------------------------------------
    async def respond_to_question(
        self, state: SessionState, question: str
    ) -> AsyncGenerator[str, None]:
        """Stream tokens for a free-form student question."""
        prompt = QUESTION_PROMPT(state, question)
        log.debug(
            "socratic_question_prompt",
            topic=state.topic_name or state.topic_id,
            step_idx=state.step_idx,
            history_len=len(state.qa_history),
        )
        async for token in self.gemini.stream_text(
            prompt=prompt, system=ARIA_BASE_PERSONA
        ):
            yield token

    async def respond_to_reply(
        self, state: SessionState, text: str
    ) -> AsyncGenerator[str, None]:
        """Stream tokens for a typed student answer / attempt."""
        prompt = REPLY_PROMPT(state, text)
        log.debug(
            "socratic_reply_prompt",
            topic=state.topic_name or state.topic_id,
            step_idx=state.step_idx,
            history_len=len(state.qa_history),
        )
        async for token in self.gemini.stream_text(
            prompt=prompt, system=ARIA_BASE_PERSONA
        ):
            yield token

    # ---- synchronous reactions ------------------------------------------------
    def respond_to_reaction(self, _state: SessionState, reaction: str) -> str:
        """Return Aria's canned response to an emoji reaction.

        Falls back to the ``confused`` reply for unknown reaction keys so the
        UI never has to deal with a 400 here.
        """
        return REACTION_RESPONSES.get(reaction, REACTION_RESPONSES["confused"])
