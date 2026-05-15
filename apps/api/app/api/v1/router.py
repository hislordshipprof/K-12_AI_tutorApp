"""Aggregator for all v1 routers.

Sub-routers each declare their own tags; importing them here keeps
`main.py` slim — just `app.include_router(v1)` and done.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    courses,
    flashcards,
    health,
    history,
    me,
    notes,
    planner,
    qa,
    quiz,
    reaction,
    reply,
    sessions,
    sketch,
    tts,
)

v1 = APIRouter(prefix="/v1")

v1.include_router(health.router)
v1.include_router(me.router)
v1.include_router(courses.router)
v1.include_router(sessions.router)
v1.include_router(qa.router)
v1.include_router(reply.router)
v1.include_router(reaction.router)
v1.include_router(sketch.router)
v1.include_router(quiz.router)
v1.include_router(tts.router)
v1.include_router(notes.router)
v1.include_router(planner.router)
v1.include_router(flashcards.router)
v1.include_router(history.router)
