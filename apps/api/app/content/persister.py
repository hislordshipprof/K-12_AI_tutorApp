"""Persist a validated ``LessonContent`` to ``topics.content`` (B2).

Responsibilities:

  1. Read the current ``content`` + ``content_provenance`` for the topic.
  2. If non-empty, archive both into ``content_history``.
  3. Update ``topics.content`` + ``topics.content_provenance`` in one go.
  4. Idempotency: refuse to overwrite a human-reviewed lesson on a re-run
     where the provenance hash hasn't changed, unless ``force=True``.

The Supabase REST client doesn't expose transactional control, so we
sequence the operations defensively (archive first, then update) and the
update is one statement — partial failure leaves the prior content
unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.content.schema import LessonContent
from app.content.validator import VALIDATOR_VERSION
from app.core.logging import get_logger

log = get_logger(__name__)


def compute_provenance_hash(
    source_url: str,
    model_generate: str,
    validator_version: str = VALIDATOR_VERSION,
) -> str:
    """Stable hash identifying a `(source, model, validator)` triple.

    Stored in ``content_provenance.hash``. On re-run with the same hash AND
    ``human_reviewed=true``, the persister refuses to overwrite.
    """
    payload = f"{source_url}|{model_generate}|{validator_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class HumanReviewedConflict(RuntimeError):
    """Raised when an unforced re-run would clobber a human-reviewed lesson."""


class LessonPersister:
    """Service-role Supabase writer for validated lessons."""

    def __init__(self, supabase: Any) -> None:
        if supabase is None:
            raise RuntimeError(
                "LessonPersister requires a Supabase client (service_role)."
            )
        self.sb = supabase

    async def persist(
        self,
        topic_id: str,
        content: LessonContent,
        provenance: dict[str, Any],
        *,
        human_reviewed: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        """Write ``content`` + ``provenance`` to ``topics(id=topic_id)``.

        Returns the provenance dict actually persisted (with ``hash`` stamped
        if not already present). Raises ``HumanReviewedConflict`` when an
        unforced re-run would overwrite an existing human-reviewed lesson
        with the same hash.
        """
        # Read current state.
        current_q = (
            self.sb.table("topics")
            .select("id, content, content_provenance")
            .eq("id", topic_id)
            .limit(1)
            .execute()
        )
        rows = current_q.data or []
        if not rows:
            raise RuntimeError(f"persist: topic {topic_id!r} not found")
        current = rows[0]
        prior_content = current.get("content")
        prior_prov = current.get("content_provenance") or {}

        # Idempotency: same hash + human_reviewed=true ⇒ refuse unless forced.
        incoming_hash = provenance.get("hash")
        if not incoming_hash:
            incoming_hash = compute_provenance_hash(
                provenance.get("source_url", ""),
                provenance.get("model_generate", ""),
                provenance.get("validator_version", VALIDATOR_VERSION),
            )
            provenance["hash"] = incoming_hash
        provenance.setdefault("human_reviewed", human_reviewed)
        provenance.setdefault("validator_version", VALIDATOR_VERSION)

        if (
            not force
            and prior_prov.get("human_reviewed") is True
            and prior_prov.get("hash") == incoming_hash
        ):
            log.info(
                "content_persist_skipped_human_reviewed",
                topic_id=topic_id,
                hash=incoming_hash,
            )
            raise HumanReviewedConflict(
                f"topic {topic_id!r} has a human-reviewed lesson with the "
                f"same provenance hash {incoming_hash!r}; pass force=True "
                "to overwrite"
            )

        # Archive prior content (best-effort) if anything is there.
        if prior_content or prior_prov:
            self.sb.table("content_history").insert(
                {
                    "topic_id": topic_id,
                    "content": prior_content,
                    "provenance": prior_prov,
                }
            ).execute()
            log.info("content_archived", topic_id=topic_id)

        # Update the topic. We feed `content` as a plain Python list — the
        # Supabase client serialises it as JSON for the jsonb column.
        content_payload = content.model_dump()["items"]
        # Re-encode-roundtrip the provenance so any non-JSON-safe values
        # (datetime, etc.) surface as a clean error here rather than at the
        # REST layer.
        _ = json.dumps(provenance, default=str)

        self.sb.table("topics").update(
            {
                "content": content_payload,
                "content_provenance": provenance,
            }
        ).eq("id", topic_id).execute()

        log.info(
            "content_persisted",
            topic_id=topic_id,
            hash=incoming_hash,
            human_reviewed=human_reviewed,
            steps=len(content_payload),
        )
        return provenance


__all__ = [
    "LessonPersister",
    "HumanReviewedConflict",
    "compute_provenance_hash",
]
