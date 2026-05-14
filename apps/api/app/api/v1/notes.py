"""Notes CRUD — Supabase-backed (with dev fallback)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.core.supabase import get_supabase, supabase_enabled
from app.models.schemas import NoteCreate, NoteOut, NoteUpdate

router = APIRouter(tags=["notes"])
log = get_logger(__name__)


# Process-local fallback (dev only).
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

    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = (
                supabase.table("notes")
                .select("*")
                .eq("user_id", str(uid))
                .order("created_at", desc=True)
                .execute()
            )
            return getattr(resp, "data", None) or []
        except Exception as e:  # noqa: BLE001
            log.warning("notes_list_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="notes unavailable",
                ) from e

    return [n for n in _NOTES.values() if n["user_id"] == uid]


@router.post(
    "/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED
)
async def create_note(
    body: NoteCreate,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    uid = _user_uuid(user)
    now = datetime.now(timezone.utc)

    payload = {
        "user_id": str(uid),
        "topic_id": str(body.topic_id) if body.topic_id else None,
        "kind": body.kind,
        "title": body.title,
        "body": body.body,
        "color": body.color,
        "pinned": body.pinned,
        "source_session_id": (
            str(body.source_session_id) if body.source_session_id else None
        ),
    }

    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = supabase.table("notes").insert(payload).execute()
            rows = getattr(resp, "data", None) or []
            if rows:
                return rows[0]
            raise RuntimeError("insert returned no rows")
        except Exception as e:  # noqa: BLE001
            log.warning("note_create_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="note create unavailable",
                ) from e

    note = {
        "id": uuid4(),
        "user_id": uid,
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
    uid = _user_uuid(user)
    patch = body.model_dump(exclude_unset=True)
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()

    supabase = get_supabase()
    if supabase is not None:
        try:
            resp = (
                supabase.table("notes")
                .update(patch)
                .eq("id", str(note_id))
                .eq("user_id", str(uid))
                .execute()
            )
            rows = getattr(resp, "data", None) or []
            if rows:
                return rows[0]
            raise HTTPException(status_code=404, detail="Note not found")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("note_update_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="note update unavailable",
                ) from e

    note = _NOTES.get(note_id)
    if note is None or note["user_id"] != uid:
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
    uid = _user_uuid(user)

    supabase = get_supabase()
    if supabase is not None:
        try:
            (
                supabase.table("notes")
                .delete()
                .eq("id", str(note_id))
                .eq("user_id", str(uid))
                .execute()
            )
            return None
        except Exception as e:  # noqa: BLE001
            log.warning("note_delete_supabase_failed", error=str(e))
            if supabase_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="note delete unavailable",
                ) from e

    note = _NOTES.get(note_id)
    if note is None or note["user_id"] != uid:
        raise HTTPException(status_code=404, detail="Note not found")
    _NOTES.pop(note_id)
    return None
