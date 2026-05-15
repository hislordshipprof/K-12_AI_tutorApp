"""Tests for the DB-backed quiz endpoints (Q3)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def _quiz_questions_query_chain(rows: list[dict[str, Any]]) -> MagicMock:
    """Build a mock chain matching `select(...).eq(...).[eq.limit.]execute()`.

    Both call shapes used by the endpoint resolve to the same `.data`
    payload — `.eq()` returns self so a longer chain still works.
    """
    chain = MagicMock(name="quiz_questions_chain")
    chain.execute.return_value = MagicMock(data=list(rows))
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    return chain


def _build_dual_table_mock(
    quiz_questions_rows: list[dict[str, Any]],
    insert_rows: list[dict[str, Any]],
) -> MagicMock:
    """Mock that routes `table("quiz_questions")` and `table("quiz_attempts")`
    to two distinct chains so a single endpoint call can hit both."""
    qq_select = _quiz_questions_query_chain(quiz_questions_rows)
    qq_table = MagicMock(name="quiz_questions_table")
    qq_table.select.return_value = qq_select

    insert_chain = MagicMock(name="quiz_attempts_insert")
    insert_chain.execute.return_value = MagicMock(data=list(insert_rows))
    qa_table = MagicMock(name="quiz_attempts_table")
    qa_table.insert.return_value = insert_chain

    def _route(name: str) -> MagicMock:
        if name == "quiz_questions":
            return qq_table
        if name == "quiz_attempts":
            return qa_table
        raise AssertionError(f"unexpected table {name!r}")

    client = MagicMock()
    client.table.side_effect = _route
    client._qq_table = qq_table
    client._qa_table = qa_table
    client._insert_chain = insert_chain
    return client


# ── GET /v1/quiz/{topic_id} ──────────────────────────────────────────────────
def test_get_quiz_returns_db_row_and_withholds_answer(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sb = _build_dual_table_mock(
        quiz_questions_rows=[
            {
                "idx": 0,
                "prompt": "What is the period $T$ of a wave?",
                "choices": ["A", "B", "C", "D"],
            }
        ],
        insert_rows=[],
    )
    monkeypatch.setattr("app.api.v1.quiz.get_supabase", lambda: sb)

    r = client.get(
        "/v1/quiz/00000000-0000-0000-0000-000000000001", headers=dev_headers
    )
    assert r.status_code == 200
    q = r.json()
    assert q["prompt"].startswith("What is the period")
    assert q["correct_idx"] is None
    assert q["explanation"] is None
    assert q["choices"] == ["A", "B", "C", "D"]


def test_get_quiz_returns_404_no_questions_when_empty(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sb = _build_dual_table_mock(quiz_questions_rows=[], insert_rows=[])
    monkeypatch.setattr("app.api.v1.quiz.get_supabase", lambda: sb)

    r = client.get(
        "/v1/quiz/00000000-0000-0000-0000-000000000099", headers=dev_headers
    )
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["code"] == "NO_QUESTIONS"


# ── POST /v1/quiz/{topic_id}/attempt ─────────────────────────────────────────
def test_submit_attempt_scores_against_real_key_and_reveals(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    topic_id = "22222222-2222-2222-2222-222222222222"
    persisted_attempt = {
        "id": "11111111-1111-1111-1111-111111111111",
        "user_id": dev_headers["X-Dev-User-Id"],
        "topic_id": topic_id,
        "question_idx": 0,
        "picked_idx": 2,
        "correct": True,
        "created_at": "2026-05-14T00:00:00+00:00",
    }
    sb = _build_dual_table_mock(
        quiz_questions_rows=[
            {"correct_idx": 2, "explanation": "Because $T = 1/f$."}
        ],
        insert_rows=[persisted_attempt],
    )
    monkeypatch.setattr("app.api.v1.quiz.get_supabase", lambda: sb)

    r = client.post(
        f"/v1/quiz/{topic_id}/attempt",
        json={"question_idx": 0, "picked_idx": 2},
        headers=dev_headers,
    )
    assert r.status_code == 200
    body = r.json()
    # Real-key scoring.
    assert body["correct"] is True
    # Reveal fields surface to client so it can render feedback.
    assert body["correct_idx"] == 2
    assert "T = 1/f" in body["explanation"]

    # The insert payload itself stored `correct=True` against quiz_attempts.
    payload = sb._insert_chain.execute.call_args  # noqa: F841 — sanity-check chain reached
    insert_payload = sb._qa_table.insert.call_args.args[0]
    assert insert_payload["picked_idx"] == 2
    assert insert_payload["correct"] is True


def test_submit_attempt_wrong_answer_is_scored_wrong(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    topic_id = "22222222-2222-2222-2222-222222222222"
    sb = _build_dual_table_mock(
        quiz_questions_rows=[
            {"correct_idx": 2, "explanation": "Because $T = 1/f$."}
        ],
        insert_rows=[
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "user_id": dev_headers["X-Dev-User-Id"],
                "topic_id": topic_id,
                "question_idx": 0,
                "picked_idx": 0,
                "correct": False,
                "created_at": "2026-05-14T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr("app.api.v1.quiz.get_supabase", lambda: sb)

    r = client.post(
        f"/v1/quiz/{topic_id}/attempt",
        json={"question_idx": 0, "picked_idx": 0},
        headers=dev_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["correct"] is False
    assert body["correct_idx"] == 2  # still revealed so UI can highlight it


def test_submit_attempt_dev_fallback_when_no_supabase(
    client: Any, dev_headers: dict[str, str]
) -> None:
    """No Supabase → endpoint returns a non-graded attempt (correct=False)."""
    r = client.post(
        "/v1/quiz/22222222-2222-2222-2222-222222222222/attempt",
        json={"question_idx": 0, "picked_idx": 0},
        headers=dev_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["correct"] is False
    assert body["picked_idx"] == 0
    # Reveal fields are None when we have no answer key.
    assert body["correct_idx"] is None
    assert body["explanation"] is None
