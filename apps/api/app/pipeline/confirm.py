"""Confirm-the-breakdown step — materialise proposed topics into rows.
(teacher-authoring pipeline, task 2.7)

`teacher-authoring.md` §5.7 / §6: after the segment job proposes a topic
breakdown, the teacher confirms it. On confirm, "a `topics` row + its
`topic_pages` are created per topic" — the human checkpoint where the model's
proposal becomes real curriculum rows the generation step then runs on.

This is the piece deferred since task 2.3 — 2.3/2.5/2.6 all CONSUME confirmed
`topics`/`topic_pages` rows; this module CREATES them. It is the service-layer
core of the §10 `POST /v1/teacher/units/{id}/topics` endpoint (the endpoint
itself is Phase 3 — Phase 2 is backend-only).

IDEMPOTENT (§13 "Teacher double-submits the confirm-breakdown step":
"`POST .../topics` is idempotent — repeating a confirm of the same breakdown
does not create duplicate topic rows"). The stable key is the proposed
topic's POSITION in the breakdown: proposed-topic[i] always maps to the
`topics` row with `n = i + 1` in the unit (`topics.n` is the unit-scoped
1-based ordinal — `unique (unit_id, n)`). A re-confirm therefore UPDATES the
existing row at that position rather than inserting a duplicate, and rewrites
its `topic_pages` to match the (possibly edited) proposed page set.

Confirmed topics start `status='draft'` (§4: a teacher-course topic created
by confirm starts `draft`, even though the `topics.status` column default is
`'published'` for Recommended courses). Generation + validation (task 2.7's
`generate_and_validate`) runs against them afterwards; publishing is a later
explicit teacher action (Phase 3).

Scope (Phase 2 is backend-only — `CLAUDE.md`): a plain service function, NO
HTTP endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────
class ConfirmError(RuntimeError):
    """The breakdown could not be confirmed.

    Carries a stable `reason` code:
      * ``no_segmentation`` — the unit has no `unit_segmentations` row, so
                              there is no proposed breakdown to confirm.
      * ``empty_breakdown`` — the latest segmentation proposed no topics
                              (§13 — "nothing teachable found here"); there is
                              nothing to materialise.
      * ``no_supabase``     — the DB function needs a Supabase client.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ConfirmResult:
    """Outcome of `confirm_breakdown`.

    `topic_ids` are the `topics` row ids, in proposed order. `created` /
    `updated` count how many rows this call inserted vs. updated — on a first
    confirm `created == len(topic_ids)` and `updated == 0`; on an idempotent
    re-confirm `created == 0` and `updated == len(topic_ids)`. `page_count`
    is the total `topic_pages` rows written across all topics.
    """

    unit_id: str
    segmentation_id: str
    topic_ids: list[str] = field(default_factory=list)
    created: int = 0
    updated: int = 0
    page_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _latest_segmentation(supabase: Any, unit_id: str) -> dict[str, Any]:
    """Load the unit's most recent `unit_segmentations` row.

    §4: "re-segmenting a unit appends a new row; the latest drives the confirm
    UI." So the confirm always works off the newest segmentation.
    """
    resp = (
        supabase.table("unit_segmentations")
        .select("id,proposed,created_at")
        .eq("unit_id", unit_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(getattr(resp, "data", None) or [])
    if not rows:
        raise ConfirmError(
            "no_segmentation",
            f"unit {unit_id} has no unit_segmentations — segment it first",
        )
    return rows[0]


def _renderable_pages(proposed_topic: dict[str, Any]) -> list[dict[str, int]]:
    """The proposed topic's page set as `{material_idx, page_idx}` dicts.

    A `ProposedTopic.pages` entry is a §2.2 `PageRef` — `material_idx` /
    `page_idx`. Only `slides`/figure pages reach here (segmentation already
    excludes prose `notes` / `practice` from a topic's page set, §6).
    """
    out: list[dict[str, int]] = []
    for p in proposed_topic.get("pages") or []:
        if not isinstance(p, dict):
            continue
        out.append(
            {
                "material_idx": int(p.get("material_idx", 0)),
                "page_idx": int(p.get("page_idx", 0)),
            }
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Confirm — materialise the proposed breakdown into topics + topic_pages.
# ─────────────────────────────────────────────────────────────────────────────
async def confirm_breakdown(
    unit_id: str,
    *,
    material_ids: list[str] | None = None,
) -> ConfirmResult:
    """Confirm a unit's latest proposed breakdown — create `topics` rows.

    The flow (`teacher-authoring.md` §5.7, §6, §13):

      1. Load the unit's LATEST `unit_segmentations`. None ->
         `ConfirmError('no_segmentation')`. An empty `proposed.topics` ->
         `ConfirmError('empty_breakdown')`.
      2. Resolve the unit's `lesson_materials` ids so a proposed topic's
         `material_idx` can be mapped to a real `material_id` for its
         `topic_pages` rows. (`material_ids` may be passed in to override the
         lookup — e.g. by the e2e script which already has them.)
      3. For each proposed topic at position `i` (0-based):
         * UPSERT a `topics` row keyed on `(unit_id, n=i+1)` — `topics.n` is
           the unit-scoped 1-based ordinal and `unique (unit_id, n)`. A first
           confirm inserts; a re-confirm of the same breakdown finds the row
           at that `n` and UPDATES it (no duplicate — §13). The row carries
           `name`, `summary`, `sort_order`, and `status='draft'` (§4 — a
           confirmed teacher topic starts draft).
         * REWRITE its `topic_pages`: delete the topic's existing rows and
           insert one per page of the proposed set (`role='slide'`,
           `ord` = display order). Re-running with an edited page set
           therefore re-syncs cleanly — still no duplicates.

    The whole call is IDEMPOTENT: a second `confirm_breakdown` of the same
    segmentation produces the SAME `topics` rows (matched on `n`) and the
    SAME `topic_pages`, never duplicates.

    Args:
        unit_id: the unit whose proposed breakdown is being confirmed.
        material_ids: optional explicit ordered list of the unit's
            `lesson_materials` ids — its index is the `material_idx` a
            proposed page references. Omitted -> loaded from the DB
            (ordered by `uploaded_at`, the same order segmentation used).

    Returns a `ConfirmResult`. Requires a configured Supabase service-role
    client.
    """
    from app.core.supabase import get_supabase

    supabase = get_supabase()
    if supabase is None:
        raise ConfirmError(
            "no_supabase",
            "confirm_breakdown requires Supabase to be configured "
            "(SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)",
        )

    # 1. The latest proposed breakdown.
    seg = _latest_segmentation(supabase, unit_id)
    seg_id = str(seg["id"])
    proposed = seg.get("proposed") or {}
    proposed_topics = [t for t in (proposed.get("topics") or []) if isinstance(t, dict)]
    if not proposed_topics:
        raise ConfirmError(
            "empty_breakdown",
            f"unit {unit_id}'s latest segmentation proposed no topics "
            f"(empty_reason: {proposed.get('empty_reason')!r}) — nothing to confirm",
        )

    # 2. Map material_idx -> material_id.
    if material_ids is None:
        mat_resp = (
            supabase.table("lesson_materials")
            .select("id,uploaded_at")
            .eq("unit_id", unit_id)
            .order("uploaded_at")
            .execute()
        )
        material_ids = [str(r["id"]) for r in (getattr(mat_resp, "data", None) or [])]

    # 3. Existing topics for this unit, indexed by `n` — so a re-confirm
    #    UPDATES the row at the proposed topic's position instead of inserting.
    existing_resp = (
        supabase.table("topics")
        .select("id,n")
        .eq("unit_id", unit_id)
        .execute()
    )
    existing_by_n: dict[int, str] = {
        int(r["n"]): str(r["id"])
        for r in (getattr(existing_resp, "data", None) or [])
        if r.get("n") is not None
    }

    topic_ids: list[str] = []
    created = 0
    updated = 0
    page_count = 0

    for i, pt in enumerate(proposed_topics):
        n = i + 1  # the unit-scoped 1-based ordinal — the stable idempotency key
        fields = {
            "unit_id": unit_id,
            "n": n,
            "name": str(pt.get("title") or f"Topic {n}"),
            "summary": str(pt.get("summary") or ""),
            "sort_order": i,
            "status": "draft",  # §4 — a confirmed teacher topic starts draft
        }

        if n in existing_by_n:
            # Re-confirm — UPDATE the row at this position. No duplicate row.
            topic_id = existing_by_n[n]
            supabase.table("topics").update(fields).eq("id", topic_id).execute()
            updated += 1
        else:
            ins = supabase.table("topics").insert(fields).execute()
            ins_rows = list(getattr(ins, "data", None) or [])
            topic_id = str(ins_rows[0]["id"]) if ins_rows else ""
            created += 1
        topic_ids.append(topic_id)

        # Rewrite the topic's `topic_pages` — delete then re-insert, so an
        # edited page set re-syncs without leaving stale rows or duplicates.
        supabase.table("topic_pages").delete().eq("topic_id", topic_id).execute()
        page_rows: list[dict[str, Any]] = []
        for ord_, page in enumerate(_renderable_pages(pt)):
            midx = page["material_idx"]
            material_id = (
                material_ids[midx]
                if 0 <= midx < len(material_ids)
                else None
            )
            if material_id is None:
                # The proposed page references a material index we cannot
                # resolve — skip it rather than write a dangling row.
                log.warning(
                    "confirm_breakdown_unresolved_material",
                    unit_id=unit_id,
                    material_idx=midx,
                )
                continue
            page_rows.append(
                {
                    "topic_id": topic_id,
                    "material_id": material_id,
                    "page_idx": page["page_idx"],
                    "role": "slide",
                    "ord": ord_,
                }
            )
        if page_rows:
            supabase.table("topic_pages").insert(page_rows).execute()
            page_count += len(page_rows)

    log.info(
        "confirm_breakdown_done",
        unit_id=unit_id,
        segmentation_id=seg_id,
        topics=len(topic_ids),
        created=created,
        updated=updated,
        pages=page_count,
    )
    return ConfirmResult(
        unit_id=unit_id,
        segmentation_id=seg_id,
        topic_ids=topic_ids,
        created=created,
        updated=updated,
        page_count=page_count,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Re-segmentation — map a fresh breakdown onto a unit's EXISTING topics
# (`teacher-authoring.md` §13, task 5.4).
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ResegmentationResult:
    """Outcome of `apply_resegmentation` — a count per mapping action.

    `topic_ids` are the added + replaced `topics` rows, in decision order.
    """

    unit_id: str
    added: int = 0
    replaced: int = 0
    retired: int = 0
    kept: int = 0
    topic_ids: list[str] = field(default_factory=list)


def _write_topic_pages(
    supabase: Any,
    topic_id: str,
    proposed_topic: dict[str, Any],
    material_ids: list[str],
) -> int:
    """Rewrite a topic's `topic_pages` from a proposed topic's page set.

    Delete-then-insert, the same re-sync `confirm_breakdown` uses. Returns
    the number of page rows written.
    """
    supabase.table("topic_pages").delete().eq("topic_id", topic_id).execute()
    page_rows: list[dict[str, Any]] = []
    for ord_, page in enumerate(_renderable_pages(proposed_topic)):
        midx = page["material_idx"]
        material_id = (
            material_ids[midx] if 0 <= midx < len(material_ids) else None
        )
        if material_id is None:
            log.warning(
                "resegment_unresolved_material",
                topic_id=topic_id,
                material_idx=midx,
            )
            continue
        page_rows.append(
            {
                "topic_id": topic_id,
                "material_id": material_id,
                "page_idx": page["page_idx"],
                "role": "slide",
                "ord": ord_,
            }
        )
    if page_rows:
        supabase.table("topic_pages").insert(page_rows).execute()
    return len(page_rows)


async def apply_resegmentation(
    unit_id: str,
    *,
    decisions: list[dict[str, Any]],
    retire_topic_ids: list[str],
    material_ids: list[str] | None = None,
) -> ResegmentationResult:
    """Apply a teacher's re-segmentation mapping (`teacher-authoring.md` §13).

    Unlike `confirm_breakdown` (the first-time confirm, which upserts topics
    by POSITION and so silently overwrites a re-segmented unit's published
    topics), this maps the latest proposed breakdown onto a unit's EXISTING
    topics by the teacher's explicit choice.

    `decisions` is one entry per proposed topic to materialise:
    `{"index": <int>, "action": "add"|"replace", "topic_id": <uuid|None>}`.
      * ``add``     — insert a brand-new `draft` `topics` row from the
                      proposal (appended after the unit's current topics).
      * ``replace`` — repoint an EXISTING topic at the proposal: rewrite its
                      `name` / `summary` / `topic_pages`, force it back to
                      `status='draft'` and clear `active_version_id`. That
                      re-arms the §4 progress reset — the topic must be
                      re-generated and re-published, and its `topic_progress`
                      rows (still tagged the now-cleared version) trigger the
                      §4 "lesson updated" reset. No row is deleted.

    `retire_topic_ids` flips existing topics to `status='retired'` — hidden
    from new students, kept for in-progress ones. Existing topics that are
    neither replaced nor retired are KEPT untouched.

    Raises `ConfirmError` on a missing / empty segmentation, an out-of-range
    proposed `index`, a `topic_id` not in the unit, or a topic mapped to
    both replace and retire.
    """
    from app.core.supabase import get_supabase

    supabase = get_supabase()
    if supabase is None:
        raise ConfirmError(
            "no_supabase", "apply_resegmentation requires Supabase to be configured"
        )

    seg = _latest_segmentation(supabase, unit_id)
    proposed_topics = [
        t
        for t in ((seg.get("proposed") or {}).get("topics") or [])
        if isinstance(t, dict)
    ]
    if not proposed_topics:
        raise ConfirmError(
            "empty_breakdown",
            f"unit {unit_id}'s latest segmentation proposed no topics",
        )

    if material_ids is None:
        mat_resp = (
            supabase.table("lesson_materials")
            .select("id,uploaded_at")
            .eq("unit_id", unit_id)
            .order("uploaded_at")
            .execute()
        )
        material_ids = [
            str(r["id"]) for r in (getattr(mat_resp, "data", None) or [])
        ]

    existing_resp = (
        supabase.table("topics").select("id,n").eq("unit_id", unit_id).execute()
    )
    existing_rows = getattr(existing_resp, "data", None) or []
    existing_ids = {str(r["id"]) for r in existing_rows}
    max_n = max(
        (int(r["n"]) for r in existing_rows if r.get("n") is not None), default=0
    )

    # ── Validate the whole mapping before mutating anything. ──
    retire_set = {str(t) for t in retire_topic_ids}
    replace_set: set[str] = set()
    for d in decisions:
        idx = int(d.get("index", -1))
        if not 0 <= idx < len(proposed_topics):
            raise ConfirmError(
                "bad_index", f"proposed-topic index {idx} is out of range"
            )
        if d.get("action") == "replace":
            tid = str(d.get("topic_id") or "")
            if tid not in existing_ids:
                raise ConfirmError(
                    "bad_topic", f"topic {tid} is not in unit {unit_id}"
                )
            replace_set.add(tid)
    for tid in retire_set:
        if tid not in existing_ids:
            raise ConfirmError(
                "bad_topic", f"topic {tid} is not in unit {unit_id}"
            )
    if replace_set & retire_set:
        raise ConfirmError(
            "conflict", "a topic cannot be both replaced and retired"
        )

    # ── Apply. ──
    added = replaced = 0
    topic_ids: list[str] = []
    next_n = max_n + 1
    for d in decisions:
        pt = proposed_topics[int(d["index"])]
        name_fields = {
            "name": str(pt.get("title") or "Untitled topic"),
            "summary": str(pt.get("summary") or ""),
        }
        if d.get("action") == "replace":
            topic_id = str(d["topic_id"])
            supabase.table("topics").update(
                {**name_fields, "status": "draft", "active_version_id": None}
            ).eq("id", topic_id).execute()
            replaced += 1
        else:  # add
            ins = (
                supabase.table("topics")
                .insert(
                    {
                        **name_fields,
                        "unit_id": unit_id,
                        "n": next_n,
                        "sort_order": next_n - 1,
                        "status": "draft",
                    }
                )
                .execute()
            )
            ins_rows = getattr(ins, "data", None) or []
            topic_id = str(ins_rows[0]["id"]) if ins_rows else ""
            next_n += 1
            added += 1
        topic_ids.append(topic_id)
        _write_topic_pages(supabase, topic_id, pt, material_ids)

    retired = 0
    for tid in retire_set:
        supabase.table("topics").update({"status": "retired"}).eq(
            "id", tid
        ).execute()
        retired += 1

    kept = len(existing_ids) - replaced - retired
    log.info(
        "apply_resegmentation_done",
        unit_id=unit_id,
        added=added,
        replaced=replaced,
        retired=retired,
        kept=kept,
    )
    return ResegmentationResult(
        unit_id=unit_id,
        added=added,
        replaced=replaced,
        retired=retired,
        kept=kept,
        topic_ids=topic_ids,
    )


__all__ = [
    "ConfirmError",
    "ConfirmResult",
    "ResegmentationResult",
    "apply_resegmentation",
    "confirm_breakdown",
]
