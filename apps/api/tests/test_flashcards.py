"""Tests for the Supabase-backed flashcards endpoints + SM-2 math."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.api.v1.flashcards import _sm2


def _build_supabase_mock(
    select_rows: list[dict[str, Any]] | None = None,
    update_rows: list[dict[str, Any]] | None = None,
) -> MagicMock:
    select_chain = MagicMock()
    for attr in ("select", "eq", "lte", "order", "limit"):
        getattr(select_chain, attr).return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=list(select_rows or []))

    update_chain = MagicMock()
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = MagicMock(data=list(update_rows or []))

    table = MagicMock()
    table.select.return_value = select_chain
    table.update.return_value = update_chain

    client = MagicMock()
    client.table.return_value = table
    client._table = table
    client._select = select_chain
    client._update = update_chain
    return client


# ─── SM-2 unit tests (pure function) ──────────────────────────────────────
def test_sm2_failure_resets_interval() -> None:
    new_ease, new_interval = _sm2(2.5, 10, 0)
    assert new_interval == 1
    assert new_ease < 2.5


def test_sm2_floor_ease_at_1_3() -> None:
    new_ease, _ = _sm2(1.3, 1, 1)
    assert new_ease >= 1.3


def test_sm2_success_grows_interval() -> None:
    new_ease, new_interval = _sm2(2.5, 6, 5)
    assert new_interval > 6
    assert new_ease >= 2.5


# ─── GET /flashcards/due ──────────────────────────────────────────────────
def test_list_due_dev_fallback(client: Any, dev_headers: dict[str, str]) -> None:
    r = client.get("/v1/flashcards/due", headers=dev_headers)
    assert r.status_code == 200
    cards = r.json()
    assert isinstance(cards, list)
    assert len(cards) >= 1


def test_list_due_filters_by_user_and_date(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sb = _build_supabase_mock(select_rows=[])
    monkeypatch.setattr("app.api.v1.flashcards.get_supabase", lambda: sb)

    r = client.get("/v1/flashcards/due", headers=dev_headers)
    assert r.status_code == 200
    sb.table.assert_called_with("flashcards")
    sb._select.eq.assert_called_with("user_id", dev_headers["X-Dev-User-Id"])
    assert sb._select.lte.called  # due_at <= today


# ─── POST /flashcards/{id}/review ─────────────────────────────────────────
def test_review_card_updates_with_sm2(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = {
        "id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
        "deck_id": "11111111-1111-1111-1111-111111111111",
        "user_id": dev_headers["X-Dev-User-Id"],
        "front": "F",
        "back": "B",
        "ease": 2.5,
        "interval_days": 6,
        "due_at": "2026-05-14",
        "last_reviewed_at": None,
        "created_at": "2026-05-14T00:00:00+00:00",
    }
    updated = {**existing, "ease": 2.6, "interval_days": 15}
    sb = _build_supabase_mock(select_rows=[existing], update_rows=[updated])
    monkeypatch.setattr("app.api.v1.flashcards.get_supabase", lambda: sb)

    r = client.post(
        "/v1/flashcards/ffffffff-ffff-ffff-ffff-ffffffffffff/review",
        json={"quality": 5},
        headers=dev_headers,
    )
    assert r.status_code == 200

    # We updated with new ease + interval, scoped to user.
    update_payload = sb._table.update.call_args.args[0]
    assert "ease" in update_payload
    assert "interval_days" in update_payload
    assert "due_at" in update_payload

    eq_calls = [c.args for c in sb._update.eq.call_args_list]
    assert ("id", "ffffffff-ffff-ffff-ffff-ffffffffffff") in eq_calls
    assert ("user_id", dev_headers["X-Dev-User-Id"]) in eq_calls


def test_review_card_404_when_card_missing(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sb = _build_supabase_mock(select_rows=[])
    monkeypatch.setattr("app.api.v1.flashcards.get_supabase", lambda: sb)
    r = client.post(
        "/v1/flashcards/00000000-0000-0000-0000-000000000000/review",
        json={"quality": 3},
        headers=dev_headers,
    )
    assert r.status_code == 404


def test_review_card_rejects_bad_quality(
    client: Any, dev_headers: dict[str, str]
) -> None:
    r = client.post(
        "/v1/flashcards/00000000-0000-0000-0000-000000000000/review",
        json={"quality": 7},
        headers=dev_headers,
    )
    # Pydantic validation catches the out-of-range value (≤5).
    assert r.status_code == 422
