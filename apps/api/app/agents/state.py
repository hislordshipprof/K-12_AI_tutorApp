"""Session state model — persisted as ``agent_state`` jsonb on ``lesson_sessions``.

A single ``SessionState`` instance represents everything Aria needs to
remember inside one tutoring session: the current topic, where we are in
the lesson plan, recent Q&A turns, hint depth, and any latent "signals"
inferred from the student's reactions / replies.

The object is intentionally a pure Pydantic model — serializable to JSON
and round-trippable through Supabase's ``jsonb`` column without surprises.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class QATurn(BaseModel):
    """One Q&A exchange in the session transcript."""

    model_config = ConfigDict(extra="ignore")

    question: str
    answer: str = ""  # Aria's full reply (joined stream).
    topic: str | None = None  # 'amplitude' | 'wavelength' | 'equation' | None
    source: Literal["text", "voice", "sketch"] = "text"


class SessionState(BaseModel):
    """Per-session agent memory persisted to Postgres jsonb."""

    model_config = ConfigDict(extra="ignore")

    # ── lesson positioning ────────────────────────────────────────────────
    topic_id: str
    topic_name: str = ""
    step_idx: int = 0
    hint_level: int = 0  # 0..3, advances when the student is stuck

    # ── transcript ────────────────────────────────────────────────────────
    qa_history: list[QATurn] = Field(default_factory=list)

    # ── inferred signals from the student's behaviour ─────────────────────
    # Shape (loose; we don't want to lock the schema down too early):
    #   {
    #     "last_reaction": "slower" | "confused" | "got_it" | "mind_blown" | None,
    #     "confusion_level": int (0–3),
    #     "mastery_estimate": float (0.0–1.0),
    #   }
    student_signals: dict[str, Any] = Field(default_factory=dict)

    # ── multimodal scratch ────────────────────────────────────────────────
    recognized_shapes: list[str] = Field(default_factory=list)

    # ── helpers ───────────────────────────────────────────────────────────
    def recent_turns(self, n: int = 3) -> list[QATurn]:
        """Return the most recent ``n`` Q&A turns (oldest → newest)."""
        if n <= 0:
            return []
        return self.qa_history[-n:]
