"""Stateful tutor agents.

This package contains the Socratic tutoring core for "Aria":

- ``state``      — Pydantic model for per-session agent state.
- ``prompts``    — System / user prompt builders + canned reactions.
- ``socratic``   — ``SocraticAgent``: pure LLM call layer (no persistence).
- ``tutor``      — ``TutorAgent``: orchestrator that owns state + routes
                   incoming events (question / reply / reaction).

The package deliberately avoids LangGraph at this phase — a small set of
methods is easier to read, test, and evolve. LangGraph remains a planned
Phase 5 upgrade once the state machine actually needs branching nodes.
"""

from app.agents.socratic import SocraticAgent
from app.agents.state import QATurn, SessionState
from app.agents.tutor import TutorAgent, get_tutor

__all__ = [
    "QATurn",
    "SessionState",
    "SocraticAgent",
    "TutorAgent",
    "get_tutor",
]
