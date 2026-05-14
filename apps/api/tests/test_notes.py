"""Tests for the Supabase-backed notes endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def _build_supabase_mock(
    select_rows: list[dict[str, Any]] | None = None,
    insert_rows: list[dict[str, Any]] | None = None,
    update_rows: list[dict[str, Any]] | None = None,
) -> MagicMock:
    select_chain = MagicMock(name="select")
    for attr in ("select", "eq", "order", "limit"):
        getattr(select_chain, attr).return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=list(select_rows or []))

    insert_chain = MagicMock(name="insert")
    insert_chain.execute.return_value = MagicMock(data=list(insert_rows or []))

    update_chain = MagicMock(name="update")
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = MagicMock(data=list(update_rows or []))

    delete_chain = MagicMock(name="delete")
    delete_chain.eq.return_value = delete_chain
    delete_chain.execute.return_value = MagicMock(data=[])

    table = MagicMock()
    table.select.return_value = select_chain
    table.insert.return_value = insert_chain
    table.update.return_value = update_chain
    table.delete.return_value = delete_chain

    client = MagicMock(name="supabase")
    client.table.return_value = table
    client._table = table
    client._select = select_chain
    client._update = update_chain
    client._delete = delete_chain
    return client


# ─── GET /notes ───────────────────────────────────────────────────────────
def test_list_notes_dev_fallback_empty(
    client: Any, dev_headers: dict[str, str]
) -> None:
    r = client.get("/v1/notes", headers=dev_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_list_notes_filters_by_user_id(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "user_id": dev_headers["X-Dev-User-Id"],
            "topic_id": None,
            "kind": "user",
            "title": "My note",
            "body": "Hello",
            "color": None,
            "pinned": False,
            "source_session_id": None,
            "created_at": "2026-05-14T00:00:00+00:00",
            "updated_at": "2026-05-14T00:00:00+00:00",
        }
    ]
    sb = _build_supabase_mock(select_rows=rows)
    monkeypatch.setattr("app.api.v1.notes.get_supabase", lambda: sb)

    r = client.get("/v1/notes", headers=dev_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1
    sb.table.assert_called_with("notes")
    sb._select.eq.assert_called_with("user_id", dev_headers["X-Dev-User-Id"])


# ─── POST /notes ──────────────────────────────────────────────────────────
def test_create_note_inserts(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    inserted = {
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "user_id": dev_headers["X-Dev-User-Id"],
        "topic_id": None,
        "kind": "user",
        "title": "Cool note",
        "body": "Body text",
        "color": "yellow",
        "pinned": False,
        "source_session_id": None,
        "created_at": "2026-05-14T00:00:00+00:00",
        "updated_at": "2026-05-14T00:00:00+00:00",
    }
    sb = _build_supabase_mock(insert_rows=[inserted])
    monkeypatch.setattr("app.api.v1.notes.get_supabase", lambda: sb)

    r = client.post(
        "/v1/notes",
        json={"body": "Body text", "title": "Cool note", "color": "yellow"},
        headers=dev_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Cool note"

    payload = sb._table.insert.call_args.args[0]
    assert payload["user_id"] == dev_headers["X-Dev-User-Id"]
    assert payload["body"] == "Body text"


# ─── PATCH /notes/{id} ────────────────────────────────────────────────────
def test_update_note_scopes_to_user(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    updated = {
        "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "user_id": dev_headers["X-Dev-User-Id"],
        "topic_id": None,
        "kind": "user",
        "title": "Renamed",
        "body": "Body",
        "color": None,
        "pinned": True,
        "source_session_id": None,
        "created_at": "2026-05-14T00:00:00+00:00",
        "updated_at": "2026-05-14T00:00:00+00:00",
    }
    sb = _build_supabase_mock(update_rows=[updated])
    monkeypatch.setattr("app.api.v1.notes.get_supabase", lambda: sb)

    r = client.patch(
        "/v1/notes/cccccccc-cccc-cccc-cccc-cccccccccccc",
        json={"title": "Renamed", "pinned": True},
        headers=dev_headers,
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"

    # Both id and user_id filters applied.
    eq_calls = [c.args for c in sb._update.eq.call_args_list]
    assert ("id", "cccccccc-cccc-cccc-cccc-cccccccccccc") in eq_calls
    assert ("user_id", dev_headers["X-Dev-User-Id"]) in eq_calls


def test_update_note_404_when_no_row(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sb = _build_supabase_mock(update_rows=[])
    monkeypatch.setattr("app.api.v1.notes.get_supabase", lambda: sb)
    r = client.patch(
        "/v1/notes/dddddddd-dddd-dddd-dddd-dddddddddddd",
        json={"title": "x"},
        headers=dev_headers,
    )
    assert r.status_code == 404


# ─── DELETE /notes/{id} ───────────────────────────────────────────────────
def test_delete_note_scoped_to_user(
    client: Any, dev_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sb = _build_supabase_mock()
    monkeypatch.setattr("app.api.v1.notes.get_supabase", lambda: sb)
    r = client.delete(
        "/v1/notes/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", headers=dev_headers
    )
    assert r.status_code == 204
    eq_calls = [c.args for c in sb._delete.eq.call_args_list]
    assert ("id", "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee") in eq_calls
    assert ("user_id", dev_headers["X-Dev-User-Id"]) in eq_calls
