"""``SocraticAgent`` — the LLM call layer.

This class is intentionally thin: it knows *how* to build a Socratic prompt
and stream the response. It does NOT know about Supabase, sessions, or
persistence — those belong to ``TutorAgent``.

Keeping the layers separate makes it trivial to unit-test the prompt
plumbing by mocking ``GeminiService.stream_text``.

B3 update: ``respond_to_question`` / ``respond_to_reply`` accept an
optional ``retrieved_chunks`` list. When chunks are present we route the
prompt through ``RAG_QUESTION_PROMPT`` so Aria anchors her nudge in
literal source material. When absent we fall back to the original
``QUESTION_PROMPT`` / ``REPLY_PROMPT`` path — graceful degradation for
topics that haven't been ingested yet.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from app.agents.prompts import (
    ARIA_BASE_PERSONA,
    QUESTION_PROMPT,
    REACTION_RESPONSES,
    REPLY_PROMPT,
)
from app.agents.state import SessionState
from app.core.logging import get_logger
from app.services.gemini import GeminiService

# NOTE: ``app.content.prompts`` re-imports ``app.agents.prompts`` for the
# persona/rules used by the lesson-generation prompt. Importing it at module
# top-level here creates a circular import via ``app.agents.__init__``. We
# load it lazily inside the methods that need it — keeps the cycle from
# closing without sacrificing readability.

log = get_logger(__name__)


class SocraticAgent:
    """Generates Aria's Socratic replies via the Gemini text model."""

    def __init__(self, gemini: GeminiService) -> None:
        self.gemini = gemini

    # ---- streaming endpoints --------------------------------------------------
    async def respond_to_question(
        self,
        state: SessionState,
        question: str,
        retrieved_chunks: list[Any] | None = None,
        slide_text: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream tokens for a free-form student question.

        When ``retrieved_chunks`` is a non-empty list, the prompt is built
        via ``RAG_QUESTION_PROMPT`` so Aria's nudge is grounded in literal
        source material. Otherwise the legacy ``QUESTION_PROMPT`` path runs.

        ``slide_text`` (plain text of the slide the student is currently
        viewing) is folded into either prompt so Aria can answer questions
        about what is on screen.
        """
        if retrieved_chunks:
            from app.content.prompts import RAG_QUESTION_PROMPT

            prompt = RAG_QUESTION_PROMPT(
                state, question, retrieved_chunks, slide_text=slide_text
            )
            rag_used = True
        else:
            prompt = QUESTION_PROMPT(state, question, slide_text=slide_text)
            rag_used = False
        log.debug(
            "socratic_question_prompt",
            topic=state.topic_name or state.topic_id,
            step_idx=state.step_idx,
            history_len=len(state.qa_history),
            rag_used=rag_used,
            rag_chunks=len(retrieved_chunks or []),
        )
        async for token in self.gemini.stream_text(
            prompt=prompt, system=ARIA_BASE_PERSONA
        ):
            yield token

    async def respond_to_reply(
        self,
        state: SessionState,
        text: str,
        retrieved_chunks: list[Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream tokens for a typed student answer / attempt.

        Reply benefits from the same source grounding as questions, so we
        accept the same optional ``retrieved_chunks`` list. The RAG prompt
        treats the student's reply as the "just asked" line — the framing
        works for both intents (asking for help vs. attempting an answer).
        """
        if retrieved_chunks:
            from app.content.prompts import RAG_QUESTION_PROMPT

            prompt = RAG_QUESTION_PROMPT(state, text, retrieved_chunks)
            rag_used = True
        else:
            prompt = REPLY_PROMPT(state, text)
            rag_used = False
        log.debug(
            "socratic_reply_prompt",
            topic=state.topic_name or state.topic_id,
            step_idx=state.step_idx,
            history_len=len(state.qa_history),
            rag_used=rag_used,
            rag_chunks=len(retrieved_chunks or []),
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
