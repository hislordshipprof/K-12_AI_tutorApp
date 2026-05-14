"""``TutorAgent`` — orchestrator for Aria's tutoring loop.

Responsibilities:
    * Load / initialize per-session ``SessionState`` from the
      ``lesson_sessions.agent_state`` jsonb column.
    * Route incoming events (question / reply / reaction) to ``SocraticAgent``.
    * Update transcript + signals + persist back to Supabase.

Design notes
------------
- This is *not* LangGraph. A LangGraph state machine is planned for Phase 5
  once we actually have branches that matter (hint escalation, tool use,
  multimodal fan-out). For Phase 3 a vanilla orchestrator is clearer.
- Supabase is optional. When credentials are missing OR a Supabase call
  raises, we log a warning and fall back to a process-local dict so dev /
  test environments keep working.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from app.agents.socratic import SocraticAgent
from app.agents.state import QATurn, SessionState
from app.core.config import settings
from app.core.logging import get_logger
from app.services.gemini import GeminiService, get_gemini

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _session_key(session_id: Any) -> str:
    """Normalize a session-id to a string key for our in-memory cache."""
    return str(session_id)


def _supabase_available() -> bool:
    """True iff the service-role key + URL are both configured."""
    return bool(
        settings.supabase_url
        and settings.supabase_service_role_key.get_secret_value()
    )


# ─────────────────────────────────────────────────────────────────────────────
# TutorAgent
# ─────────────────────────────────────────────────────────────────────────────
class TutorAgent:
    """Routes events, manages session state, owns the ``SocraticAgent``.

    The Supabase client is injected lazily so unit tests can pass ``None``
    (or a MagicMock) without touching the real factory.
    """

    def __init__(
        self,
        gemini: GeminiService,
        supabase: Any | None = None,
    ) -> None:
        self.gemini = gemini
        self.supabase = supabase
        self.socratic = SocraticAgent(gemini)
        # In-process fallback when Supabase isn't reachable / configured.
        # Keyed by stringified session_id.
        self._memory: dict[str, SessionState] = {}

    # ── state load / save ────────────────────────────────────────────────
    async def get_or_init_state(
        self,
        session_id: Any,
        user_id: str,
        topic_id: str | None = None,
    ) -> SessionState:
        """Read ``agent_state`` from Supabase, or initialize a fresh state.

        Falls back to the in-memory cache on any Supabase failure. The
        ``user_id`` is currently unused at the persistence layer (RLS would
        scope rows on the DB side) but is kept in the signature for future
        use and observability.
        """
        key = _session_key(session_id)

        # 1. Try Supabase first.
        # NOTE: We use the service-role client, which bypasses RLS, so we
        # MUST scope the query by user_id ourselves. The handler already
        # ran `require_session_owner` — this filter is defense-in-depth.
        if self.supabase is not None and user_id:
            try:
                resp = (
                    self.supabase.table("lesson_sessions")
                    .select("id,topic_id,agent_state")
                    .eq("id", str(session_id))
                    .eq("user_id", str(user_id))
                    .limit(1)
                    .execute()
                )
                rows = getattr(resp, "data", None) or []
                if rows:
                    row = rows[0]
                    raw_state = row.get("agent_state") or {}
                    db_topic = row.get("topic_id")
                    if raw_state:
                        try:
                            state = SessionState.model_validate(raw_state)
                            # Keep topic_id consistent with the DB row if blank.
                            if not state.topic_id and db_topic:
                                state.topic_id = str(db_topic)
                            log.debug(
                                "tutor_state_loaded",
                                session_id=key,
                                history_len=len(state.qa_history),
                            )
                            return state
                        except Exception:  # noqa: BLE001 — fall through to init
                            log.warning(
                                "tutor_state_parse_failed",
                                session_id=key,
                            )
                    # Row exists but has no state yet — initialise from DB topic.
                    return SessionState(
                        topic_id=str(db_topic or topic_id or ""),
                    )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "tutor_state_supabase_unavailable",
                    session_id=key,
                    error=str(e),
                )

        # 2. In-memory cache fallback.
        if key in self._memory:
            return self._memory[key]

        # 3. First-touch initialisation.
        state = SessionState(topic_id=str(topic_id or ""))
        self._memory[key] = state
        log.info(
            "tutor_state_initialised",
            session_id=key,
            user_id=user_id,
            topic_id=state.topic_id,
            persisted=False,
        )
        return state

    async def save_state(
        self,
        session_id: Any,
        state: SessionState,
        user_id: str | None = None,
    ) -> None:
        """Persist ``state`` back to Supabase; cache locally as a backup.

        When `user_id` is provided we scope the UPDATE to that user as
        defense-in-depth against IDOR (service-role bypasses RLS).
        """
        key = _session_key(session_id)
        # Always update local cache so a Supabase outage doesn't lose progress.
        self._memory[key] = state

        if self.supabase is None:
            log.debug("tutor_state_saved_memory_only", session_id=key)
            return

        try:
            payload = state.model_dump(mode="json")
            q = (
                self.supabase.table("lesson_sessions")
                .update({"agent_state": payload})
                .eq("id", str(session_id))
            )
            if user_id:
                q = q.eq("user_id", str(user_id))
            q.execute()
            log.debug("tutor_state_saved", session_id=key)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "tutor_state_save_failed",
                session_id=key,
                error=str(e),
            )

    # ── event handlers ───────────────────────────────────────────────────
    async def handle_question(
        self,
        session_id: Any,
        user_id: str,
        question: str,
        source: str = "text",
        topic_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream Aria's Socratic response to a free-form question.

        Records the full transcript turn after streaming completes.
        """
        state = await self.get_or_init_state(session_id, user_id, topic_id=topic_id)

        collected: list[str] = []
        async for token in self.socratic.respond_to_question(state, question):
            collected.append(token)
            yield token

        full = "".join(collected)
        state.qa_history.append(
            QATurn(
                question=question,
                answer=full,
                source=source if source in ("text", "voice", "sketch") else "text",
            )
        )
        await self.save_state(session_id, state, user_id=user_id)

    async def handle_reply(
        self,
        session_id: Any,
        user_id: str,
        text: str,
        topic_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream Aria's Socratic response to a typed student reply."""
        state = await self.get_or_init_state(session_id, user_id, topic_id=topic_id)

        collected: list[str] = []
        async for token in self.socratic.respond_to_reply(state, text):
            collected.append(token)
            yield token

        full = "".join(collected)
        # Synthetic 'question' label keeps the transcript readable: it's
        # not a real question — it's what the student SAID.
        state.qa_history.append(
            QATurn(
                question=f"(student said: {text})",
                answer=full,
                source="text",
            )
        )
        await self.save_state(session_id, state, user_id=user_id)

    async def handle_reaction(
        self,
        session_id: Any,
        user_id: str,
        reaction: str,
        topic_id: str | None = None,
    ) -> str:
        """Apply an emoji reaction → update signals → return canned response."""
        state = await self.get_or_init_state(session_id, user_id, topic_id=topic_id)

        signals = dict(state.student_signals or {})
        signals["last_reaction"] = reaction

        # Crude confusion heuristic — bump on negative reactions, reset on positive.
        conf = int(signals.get("confusion_level") or 0)
        if reaction == "confused":
            conf = min(conf + 2, 3)
        elif reaction == "slower":
            conf = min(conf + 1, 3)
        elif reaction in ("got_it", "mind_blown"):
            conf = max(conf - 1, 0)
        signals["confusion_level"] = conf

        # Bump hint level when student keeps asking for slower / confused signals.
        if reaction in ("slower", "confused"):
            state.hint_level = min(state.hint_level + 1, 3)

        state.student_signals = signals
        await self.save_state(session_id, state, user_id=user_id)

        return self.socratic.respond_to_reaction(state, reaction)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton + FastAPI dependency
# ─────────────────────────────────────────────────────────────────────────────
_tutor_singleton: TutorAgent | None = None


def _maybe_supabase() -> Any | None:
    """Build the admin Supabase client lazily; return ``None`` on failure.

    Failure here is *expected* in unit / dev environments without secrets.
    The TutorAgent will gracefully fall back to its in-memory cache.
    """
    if not _supabase_available():
        log.info("tutor_supabase_disabled", reason="missing_credentials")
        return None
    try:
        from app.services.supabase import get_supabase_admin

        return get_supabase_admin()
    except Exception as e:  # noqa: BLE001
        log.warning("tutor_supabase_init_failed", error=str(e))
        return None


def get_tutor() -> TutorAgent:
    """FastAPI dependency: return the cached ``TutorAgent`` singleton.

    Production code uses this directly via ``Depends(get_tutor)``. Tests
    that want to inject custom dependencies should construct a
    ``TutorAgent(...)`` themselves — see ``build_tutor`` for a convenience
    wrapper that handles the lazy Supabase init.
    """
    global _tutor_singleton
    if _tutor_singleton is None:
        _tutor_singleton = TutorAgent(
            gemini=get_gemini(),
            supabase=_maybe_supabase(),
        )
    return _tutor_singleton


def build_tutor(
    gemini: GeminiService | None = None,
    supabase: Any | None = None,
) -> TutorAgent:
    """Construct a NON-cached ``TutorAgent`` — useful in tests."""
    return TutorAgent(
        gemini=gemini or get_gemini(),
        supabase=supabase if supabase is not None else _maybe_supabase(),
    )


def _looks_like_uuid(value: Any) -> bool:
    """Small helper used by routes to gate user-id parsing."""
    try:
        UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True
