"""Pydantic v2 schemas mirroring the Supabase Postgres tables.

Read/Write variants are split where useful — e.g., `NoteCreate` (client →
server) vs `NoteOut` (server → client, including server-generated fields).

Schema names are deliberately *singular* to match SQL row semantics.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Common ────────────────────────────────────────────────────────────────────
ISO = Annotated[datetime, Field(description="ISO-8601 timestamp (UTC).")]


class ORMModel(BaseModel):
    """Base for DB-row schemas — allows population from object attributes."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")


# ── profiles ──────────────────────────────────────────────────────────────────
class ProfileOut(ORMModel):
    id: UUID
    full_name: str | None = None
    grade: str | None = None
    goal: str | None = None
    streak_days: int = 0
    last_active: datetime | None = None
    avatar_color: str | None = None
    created_at: ISO
    updated_at: ISO


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    grade: str | None = None
    goal: str | None = None
    avatar_color: str | None = None


# ── courses / units / topics ─────────────────────────────────────────────────
class CourseOut(ORMModel):
    id: UUID
    slug: str
    title: str
    exam: str | None = None
    color_gradient: str | None = None
    icon_emoji: str | None = None
    sort_order: int = 0
    created_at: ISO


class UnitOut(ORMModel):
    id: UUID
    course_id: UUID
    n: int
    name: str
    sort_order: int = 0
    created_at: ISO


class TopicOut(ORMModel):
    id: UUID
    unit_id: UUID
    n: int
    name: str
    duration_min: int | None = None
    summary: str | None = None
    content: list[dict[str, Any]] | dict[str, Any] | None = None
    sort_order: int = 0
    created_at: ISO


# ── enrollments ──────────────────────────────────────────────────────────────
class EnrollmentCreate(BaseModel):
    course_id: UUID
    target_score: str | None = None


class EnrollmentOut(ORMModel):
    id: UUID
    user_id: UUID
    course_id: UUID
    started_at: ISO
    target_score: str | None = None
    created_at: ISO


# ── topic_progress ───────────────────────────────────────────────────────────
TopicStatus = Literal["not_started", "in_progress", "done"]


class TopicProgressOut(ORMModel):
    id: UUID
    user_id: UUID
    topic_id: UUID
    status: TopicStatus
    score: int | None = None
    time_spent_s: int = 0
    last_step_idx: int = 0
    completed_at: datetime | None = None
    updated_at: ISO
    created_at: ISO


class TopicProgressUpdate(BaseModel):
    status: TopicStatus | None = None
    score: int | None = None
    time_spent_s: int | None = None
    last_step_idx: int | None = None


# ── lesson_sessions ──────────────────────────────────────────────────────────
class SessionStartRequest(BaseModel):
    topic_id: UUID


class SessionOut(ORMModel):
    id: UUID
    user_id: UUID
    topic_id: UUID
    started_at: ISO
    ended_at: datetime | None = None
    agent_state: dict[str, Any] = Field(default_factory=dict)
    created_at: ISO


class SessionEndRequest(BaseModel):
    agent_state: dict[str, Any] | None = None


# ── qa_questions ─────────────────────────────────────────────────────────────
QASource = Literal["text", "voice", "sketch"]


class QARequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    source: QASource = "text"


class QAOut(ORMModel):
    id: UUID
    session_id: UUID
    q_text: str
    q_audio_url: str | None = None
    a_text: str | None = None
    a_topic: str | None = None
    source: QASource
    created_at: ISO


# ── sketches ─────────────────────────────────────────────────────────────────
class SketchCreate(BaseModel):
    svg_data: str
    png_data_url: str | None = None
    question: str | None = Field(default=None, max_length=2000)


class SketchOut(ORMModel):
    id: UUID
    session_id: UUID
    svg_data: str
    png_data_url: str | None = None
    recognized_shape: str | None = None
    ai_response: str | None = None
    created_at: ISO


# ── quizzes ──────────────────────────────────────────────────────────────────
class QuizQuestion(BaseModel):
    idx: int
    prompt: str
    choices: list[str]
    correct_idx: int | None = Field(
        default=None,
        description="Withheld from clients until they submit an attempt.",
    )
    explanation: str | None = None


class QuizAttemptIn(BaseModel):
    question_idx: int
    picked_idx: int


class QuizAttemptOut(ORMModel):
    id: UUID
    user_id: UUID
    topic_id: UUID
    question_idx: int
    picked_idx: int | None = None
    correct: bool | None = None
    created_at: ISO


# ── notes ────────────────────────────────────────────────────────────────────
NoteKind = Literal["auto", "user", "qa", "aria"]


class NoteCreate(BaseModel):
    topic_id: UUID | None = None
    kind: NoteKind = "user"
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    color: str | None = None
    pinned: bool = False
    source_session_id: UUID | None = None


class NoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    color: str | None = None
    pinned: bool | None = None


class NoteOut(ORMModel):
    id: UUID
    user_id: UUID
    topic_id: UUID | None = None
    kind: NoteKind
    title: str | None = None
    body: str | None = None
    color: str | None = None
    pinned: bool = False
    source_session_id: UUID | None = None
    created_at: ISO
    updated_at: ISO


# ── decks / flashcards ───────────────────────────────────────────────────────
class DeckCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    topic_ids: list[UUID] = Field(default_factory=list)


class DeckOut(ORMModel):
    id: UUID
    user_id: UUID
    name: str
    topic_ids: list[UUID] = Field(default_factory=list)
    created_at: ISO


class FlashcardCreate(BaseModel):
    deck_id: UUID
    front: str = Field(min_length=1, max_length=1000)
    back: str = Field(min_length=1, max_length=4000)


class FlashcardOut(ORMModel):
    id: UUID
    deck_id: UUID
    user_id: UUID
    front: str
    back: str
    ease: float = 2.5
    interval_days: int = 1
    due_at: date
    last_reviewed_at: datetime | None = None
    created_at: ISO


class FlashcardReview(BaseModel):
    """SM-2 review submission. `quality` is the 0–5 rating."""

    quality: int = Field(ge=0, le=5)


# ── schedule_blocks ──────────────────────────────────────────────────────────
ScheduleKind = Literal["lesson", "quiz", "flashcards", "office_hours", "rest"]
ScheduleStatus = Literal["planned", "done", "skipped"]


class ScheduleBlockOut(ORMModel):
    id: UUID
    user_id: UUID
    date: date
    start_time: time | None = None
    duration_min: int | None = None
    kind: ScheduleKind
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ScheduleStatus = "planned"
    created_at: ISO


class PlannerWeekOut(BaseModel):
    week_start: date
    blocks: list[ScheduleBlockOut]


class PlannerRegenerateRequest(BaseModel):
    week_start: date | None = None
    focus_topic_ids: list[UUID] = Field(default_factory=list)


# ── agent_traces (server-internal) ───────────────────────────────────────────
class AgentTraceOut(ORMModel):
    id: UUID
    session_id: UUID | None = None
    user_id: UUID | None = None
    step: str | None = None
    agent: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    latency_ms: int | None = None
    created_at: ISO


# ── generic envelopes ────────────────────────────────────────────────────────
class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    request_id: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    models: dict[str, str]
    version: str
