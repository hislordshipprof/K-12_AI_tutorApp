"""Notes CRUD — in-memory stub. Replaced by Supabase in a later phase."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.models.schemas import NoteCreate, NoteOut, NoteUpdate

router = APIRouter(tags=["notes"])

_NOTES: dict[UUID, dict[str, Any]] = {}


def _user_uuid(user: dict[str, Any]) -> UUID:
    try:
        return UUID(str(user["sub"]))
    except (ValueError, KeyError, TypeError):
        return uuid4()


@router.get("/notes", response_model=list[NoteOut])
async def list_notes(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    uid = _user_uuid(user)
    return [n for n in _NOTES.values() if n["user_id"] == uid]


@router.post("/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(
    body: NoteCreate,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    note = {
        "id": uuid4(),
        "user_id": _user_uuid(user),
        "topic_id": body.topic_id,
        "kind": body.kind,
        "title": body.title,
        "body": body.body,
        "color": body.color,
        "pinned": body.pinned,
        "source_session_id": body.source_session_id,
        "created_at": now,
        "updated_at": now,
    }
    _NOTES[note["id"]] = note
    return note


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: UUID,
    body: NoteUpdate,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    note = _NOTES.get(note_id)
    if note is None or note["user_id"] != _user_uuid(user):
        raise HTTPException(status_code=404, detail="Note not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        note[k] = v
    note["updated_at"] = datetime.now(timezone.utc)
    return note


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> None:
    note = _NOTES.get(note_id)
    if note is None or note["user_id"] != _user_uuid(user):
        raise HTTPException(status_code=404, detail="Note not found")
    _NOTES.pop(note_id)
