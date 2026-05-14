"""Tests for the Supabase-backed quiz endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def _build_supabase_mock(insert_rows: list[dict[str, Any]]) -> MagicMock:
    insert_chain = MagicMock(name="insert")
    insert_chain.execute.return_value = MagicMock(data=list(insert_rows))

    table = MagicMock()
    table.insert.return_value = insert_chain

    client = MagicMock()
    client.table.return_value = table
    client._table = table
    return client


def test_get_quiz_question_withholds_answer(
    client: Any, dev_headers: dict[str, str]
) -> None:
    r = client.get(
        "/v1/quiz/00000000-0000-0000-0000-000000000001", headers=dev_headers
    )
    assert r.status_code == 200
    q = r.json()
    assert q["correct_idx"] is None
    assert q["explanation"] is None
    assert len(q["choices"]) >= 2


def test_submit_attempt_persists_to_supabase(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    persisted = {
        "id": "11111111-1111-1111-1111-111111111111",
        "user_id": dev_headers["X-Dev-User-Id"],
        "topic_id": "22222222-2222-2222-2222-222222222222",
        "question_idx": 0,
        "picked_idx": 2,
        "correct": True,
        "created_at": "2026-05-14T00:00:00+00:00",
    }
    sb = _build_supabase_mock([persisted])
    monkeypatch.setattr("app.api.v1.quiz.get_supabase", lambda: sb)

    r = client.post(
        "/v1/quiz/22222222-2222-2222-2222-222222222222/attempt",
        json={"question_idx": 0, "picked_idx": 2},
        headers=dev_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["correct"] is True

    sb.table.assert_called_with("quiz_attempts")
    payload = sb._table.insert.call_args.args[0]
    assert payload["user_id"] == dev_headers["X-Dev-User-Id"]
    assert payload["topic_id"] == "22222222-2222-2222-2222-222222222222"
    assert payload["picked_idx"] == 2
    assert payload["correct"] is True


def test_submit_attempt_dev_fallback(
    client: Any, dev_headers: dict[str, str]
) -> None:
    """No Supabase → still returns a scored attempt (dev mode)."""
    r = client.post(
        "/v1/quiz/22222222-2222-2222-2222-222222222222/attempt",
        json={"question_idx": 0, "picked_idx": 0},
        headers=dev_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["correct"] is False
    assert body["picked_idx"] == 0
