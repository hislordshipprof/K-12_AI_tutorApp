"""End-to-end pipeline proof — upload to validated draft lessons (task 2.7).

Task 2.7 *Verify*: "run the full script, review the lessons." This script is
the runnable proof that the WHOLE teacher-authoring pipeline works on one real
unit — the `Unit 8 - Fluids - AP Physics 1.pptx` deck — before any UI is
built (Phase 3).

It chains every Phase 2 stage on the real deck:

    ingest (2.1) -> segment (2.2) -> confirm (2.7) -> generate (2.5)
                                                   -> validate (2.7)

for ALL the topics segmentation proposes, and prints a per-topic report —
the steps generated, validated vs. gap-reported, the gap report on a failure.

It hangs the run off a clearly-named DEMO teacher course + unit (a fixed
slug, `e2e-fluids-demo`) and is IDEMPOTENT / re-runnable — a second run reuses
the demo course/unit (and the idempotent `confirm_breakdown` reuses the
`topics` rows), so it does not pile up duplicate courses or topics.

Flags:
  * ``--max-topics N`` — generate + validate only the first N proposed
    topics (default: all). The whole deck is many PRO-model calls; this caps
    a smoke run.
  * ``--starved-topic`` — additionally run ONE topic through a deliberately
    FAILING validation: its normally-generated lesson is graded against the
    WHOLE unit's key points (every topic's, far more than one topic's pages
    cover), so it cannot pass. The topic fails validation, the retry fails the
    same way, and it lands `draft` with a gap report — task 2.7 acceptance
    criterion 2. (Emptying the generator's slice does NOT starve it — the
    generator also reads the slide images — so the failure is injected on the
    validation side, deterministically, using only real key points.)

Run (the real deck path is the default):
    python -m app.pipeline.e2e_script
    python -m app.pipeline.e2e_script "C:/path/Unit 8 - Fluids - AP Physics 1.pptx"
    python -m app.pipeline.e2e_script --max-topics 2 --starved-topic

This makes MANY live Gemini calls (one comprehension call + a PRO call per
topic for generation + a PRO call per topic for validation). The orchestrator
runs the live Fluids proof — the unit tests use a mocked Gemini.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import secrets
import sys
import uuid
from pathlib import Path
from typing import Any

from app.pipeline.confirm import ConfirmError, confirm_breakdown
from app.pipeline.generate import ComprehensionSlice, SliceSection
from app.pipeline.ingest import ingest_material
from app.pipeline.segment import SegmentError, segment_unit
from app.pipeline.validate import generate_and_validate

# The default real deck — task 2.7 names this exact file.
_DEFAULT_DECK = r"C:\Users\chica\Downloads\Unit 8 - Fluids - AP Physics 1.pptx"

# The fixed demo course/unit the run hangs off — a stable slug so a re-run
# reuses them rather than creating duplicates.
_DEMO_COURSE_SLUG = "e2e-fluids-demo"
_DEMO_COURSE_TITLE = "[E2E demo] AP Physics 1 — Fluids"
_DEMO_UNIT_NAME = "Unit 8 — Fluids"
_DEMO_TEACHER_EMAIL = "e2e-fluids-demo-teacher@edutest-qa.dev"
_DEMO_TEACHER_NAME = "[E2E demo] Fluids Teacher"


def _ensure_demo_teacher(supabase: Any) -> str:
    """Find-or-create the demo teacher — a REAL `profiles` row. Idempotent.

    `lesson_materials.uploaded_by` and `courses.owner_id` are FKs to
    `profiles(id)`, and `profiles.id` is itself a FK to `auth.users(id)` —
    so the demo teacher MUST be a real auth user, not a synthetic uuid.
    User creation is owned by Supabase Auth: the service role creates one
    via the Auth admin API and the `handle_new_user` trigger then writes
    the matching `public.profiles` row (`full_name` from the user metadata),
    which is updated to `role='teacher'`.

    Idempotency: the existing demo teacher is found by its marker
    `profiles.full_name` (a plain PostgREST query — the Auth admin
    `list_users` is not reliably available). Only a genuinely absent
    teacher is created, so a re-run reuses the same row.
    """
    found = (
        supabase.table("profiles")
        .select("id")
        .eq("full_name", _DEMO_TEACHER_NAME)
        .limit(1)
        .execute()
    )
    rows = list(getattr(found, "data", None) or [])
    if rows:
        tid = str(rows[0]["id"])
        supabase.table("profiles").update({"role": "teacher"}).eq("id", tid).execute()
        return tid

    created = supabase.auth.admin.create_user(
        {
            "email": _DEMO_TEACHER_EMAIL,
            "password": secrets.token_urlsafe(18),
            "email_confirm": True,
            "user_metadata": {"full_name": _DEMO_TEACHER_NAME},
        }
    )
    tid = str(created.user.id)
    supabase.table("profiles").update({"role": "teacher"}).eq("id", tid).execute()
    return tid


def _reconfigure_stdout() -> None:
    """UTF-8 stdout so unicode in lesson text renders on Windows consoles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _ensure_demo_course_unit(supabase: Any, teacher_id: str) -> tuple[str, str]:
    """Find-or-create the demo teacher course + its unit. Idempotent.

    Keyed on the fixed `_DEMO_COURSE_SLUG` (`courses.slug` is unique), so a
    re-run REUSES the existing course/unit instead of stacking duplicates.
    The course is created as a teacher course (`origin='teacher'`,
    `owner_id=teacher_id`, `subject='Physics'`, `grade_band='9-12'`) so the
    persona builder and the rest of the teacher pipeline treat it correctly.

    Returns `(course_id, unit_id)`.
    """
    # Course — find by slug, else insert.
    course_resp = (
        supabase.table("courses")
        .select("id")
        .eq("slug", _DEMO_COURSE_SLUG)
        .limit(1)
        .execute()
    )
    course_rows = list(getattr(course_resp, "data", None) or [])
    if course_rows:
        course_id = str(course_rows[0]["id"])
        # Re-run / a prior run before the owner was wired — ensure ownership.
        supabase.table("courses").update({"owner_id": teacher_id}).eq(
            "id", course_id
        ).execute()
    else:
        course_id = str(uuid.uuid4())
        supabase.table("courses").insert(
            {
                "id": course_id,
                "slug": _DEMO_COURSE_SLUG,
                "title": _DEMO_COURSE_TITLE,
                "origin": "teacher",
                "owner_id": teacher_id,
                "subject": "Physics",
                "grade_band": "9-12",
                "teaching_style": (
                    "I scaffold from everyday intuition to the formal "
                    "physics, asking a guiding question before each new idea."
                ),
                "created_at": _now(),
            }
        ).execute()

    # Unit — find by (course_id, n=1), else insert.
    unit_resp = (
        supabase.table("units")
        .select("id")
        .eq("course_id", course_id)
        .eq("n", 1)
        .limit(1)
        .execute()
    )
    unit_rows = list(getattr(unit_resp, "data", None) or [])
    if unit_rows:
        unit_id = str(unit_rows[0]["id"])
    else:
        unit_id = str(uuid.uuid4())
        supabase.table("units").insert(
            {
                "id": unit_id,
                "course_id": course_id,
                "n": 1,
                "name": _DEMO_UNIT_NAME,
                "created_at": _now(),
            }
        ).execute()

    return course_id, unit_id


def _existing_material(supabase: Any, unit_id: str, filename: str) -> dict[str, Any] | None:
    """Return an already-`converted` material row for this file, if any.

    Lets a re-run skip the (slow) re-ingest of the same deck — the material
    is uploaded once and reused.
    """
    resp = (
        supabase.table("lesson_materials")
        .select("id,filename,conversion_status,normalized_pdf")
        .eq("unit_id", unit_id)
        .execute()
    )
    for r in getattr(resp, "data", None) or []:
        if r.get("filename") == filename and r.get("conversion_status") == "converted":
            return r
    return None


def _over_broad_validation_slice(supabase: Any, unit_id: str) -> ComprehensionSlice:
    """The WHOLE unit's key points as one slice — deliberately too wide.

    Task 2.7 acceptance criterion 2 needs a topic that reliably FAILS
    validation. A topic's lesson is generated from, and normally graded
    against, its OWN handful of key points (the Bug B fix). Grading that same
    lesson against EVERY topic's key points instead guarantees gaps — the
    lesson genuinely does not teach the other topics — so it fails the first
    validation, the retry fails identically, and the topic lands `draft` with
    a gap report. Deterministic, and built only from real key points (no
    fabricated content).
    """
    resp = (
        supabase.table("unit_segmentations")
        .select("proposed,created_at")
        .eq("unit_id", unit_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(getattr(resp, "data", None) or [])
    proposed = (rows[0].get("proposed") if rows else {}) or {}
    sections: list[SliceSection] = []
    for t in proposed.get("topics") or []:
        if not isinstance(t, dict):
            continue
        kps = [str(k) for k in (t.get("key_points") or []) if str(k).strip()]
        if kps:
            sections.append(
                SliceSection(title=str(t.get("title") or ""), key_points=kps)
            )
    return ComprehensionSlice(sections=sections, figures=[])


async def run(deck_path: str, max_topics: int | None, starved: bool) -> int:
    from app.core.supabase import get_supabase

    supabase = get_supabase()
    if supabase is None:
        print(
            "[e2e] Supabase is not configured — set SUPABASE_URL + "
            "SUPABASE_SERVICE_ROLE_KEY",
            file=sys.stderr,
        )
        return 3

    src = Path(deck_path)
    if not src.is_file():
        print(f"[e2e] deck not found: {src}", file=sys.stderr)
        return 2

    # 0. The demo teacher (a real profiles row) + course + unit (idempotent).
    teacher_id = _ensure_demo_teacher(supabase)
    course_id, unit_id = _ensure_demo_course_unit(supabase, teacher_id)
    print(
        f"[e2e] demo teacher={teacher_id} course={course_id} unit={unit_id} "
        f"(slug={_DEMO_COURSE_SLUG!r})",
        file=sys.stderr,
    )

    # 1. INGEST — validate + normalize the deck to PDF, write a
    #    `lesson_materials` row. Skip if the deck is already ingested.
    existing = _existing_material(supabase, unit_id, src.name)
    if existing is not None:
        print(
            f"[e2e] ingest: reusing already-converted material "
            f"{existing['id']} ({src.name})",
            file=sys.stderr,
        )
    else:
        print(f"[e2e] ingest: {src.name} ...", file=sys.stderr)
        ingest = ingest_material(
            unit_id=unit_id,
            teacher_id=teacher_id,
            filename=src.name,
            data=src.read_bytes(),
            kind="slides",
        )
        if ingest.conversion_status != "converted":
            print(
                f"[e2e] INGEST FAILED ({ingest.conversion_status}): "
                f"{ingest.error}",
                file=sys.stderr,
            )
            return 4
        print(f"[e2e] ingest: converted -> {ingest.normalized_pdf}", file=sys.stderr)

    # 2. SEGMENT — one combined multimodal call -> a proposed breakdown.
    print("[e2e] segment: comprehending the unit (ONE multimodal call) ...",
          file=sys.stderr)
    try:
        seg = await segment_unit(unit_id)
    except SegmentError as e:
        print(f"[e2e] SEGMENTATION FAILED ({e.reason}): {e}", file=sys.stderr)
        return 5
    if seg.empty_reason:
        print(f"[e2e] segment: EMPTY breakdown — {seg.empty_reason}", file=sys.stderr)
        return 6
    print(f"[e2e] segment: proposed {seg.topic_count} topic(s)", file=sys.stderr)

    # 3. CONFIRM — materialise the proposed breakdown into topics +
    #    topic_pages. Idempotent — a re-run reuses the rows.
    try:
        confirmed = await confirm_breakdown(unit_id)
    except ConfirmError as e:
        print(f"[e2e] CONFIRM FAILED ({e.reason}): {e}", file=sys.stderr)
        return 7
    print(
        f"[e2e] confirm: {len(confirmed.topic_ids)} topic(s) "
        f"(created={confirmed.created} updated={confirmed.updated}, "
        f"{confirmed.page_count} topic_pages)",
        file=sys.stderr,
    )

    topic_ids = confirmed.topic_ids
    if max_topics is not None:
        topic_ids = topic_ids[:max_topics]

    # 4. GENERATE + VALIDATE every (selected) topic — retry-once-then-draft.
    print(
        f"[e2e] generate + validate {len(topic_ids)} topic(s) "
        f"(each = PRO-model generation + validation) ...\n",
        file=sys.stderr,
    )
    results: list[tuple[str, Any]] = []
    for i, tid in enumerate(topic_ids, 1):
        name = _topic_name(supabase, tid)
        print(f"[e2e]  ({i}/{len(topic_ids)}) {name} ...", file=sys.stderr)
        gv = await generate_and_validate(tid)
        results.append((name, gv))

    # 5. The STARVED topic (acceptance criterion 2) — generate one topic
    #    normally, then grade it against the WHOLE unit's key points so it
    #    FAILS validation and lands `draft` with a gap report.
    starved_result: tuple[str, Any] | None = None
    if starved and confirmed.topic_ids:
        starved_tid = confirmed.topic_ids[0]
        starved_name = _topic_name(supabase, starved_tid)
        print(
            f"\n[e2e] STARVED run on {starved_name!r} — grading its lesson "
            "against the WHOLE unit's key points (must fail validation) ...",
            file=sys.stderr,
        )
        over_broad = _over_broad_validation_slice(supabase, unit_id)
        gv = await generate_and_validate(
            starved_tid, validation_slice=over_broad
        )
        starved_result = (starved_name, gv)

    # ── Per-topic report ─────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("E2E PIPELINE REPORT — Unit 8: Fluids")
    print("=" * 72)
    all_validated = True
    for name, gv in results:
        status = "VALIDATED" if gv.passed else "GAP-REPORTED"
        if not gv.passed:
            all_validated = False
        print(
            f"\n  • {name}\n"
            f"      steps={gv.generate.step_count} "
            f"slide-backed={gv.generate.slide_backed} "
            f"attempts={gv.attempts}  -> {status}  (status=draft)"
        )
        if not gv.passed:
            print("      " + gv.report.gap_report_text().replace("\n", "\n      "))

    if starved_result is not None:
        name, gv = starved_result
        ok = (not gv.passed) and bool(gv.report.gaps)
        print(
            f"\n  • [STARVED] {name}\n"
            f"      attempts={gv.attempts}  -> "
            f"{'GAP-REPORTED (expected)' if ok else 'UNEXPECTEDLY PASSED'}  "
            f"(status=draft)"
        )
        print("      " + gv.report.gap_report_text().replace("\n", "\n      "))
        if not ok:
            print(
                "\n[e2e] FAIL — the starved topic was expected to fail "
                "validation with a gap report.",
                file=sys.stderr,
            )
            return 8

    print("\n" + "=" * 72)
    if all_validated:
        print("[e2e] OK — every proposed topic generated a VALIDATED draft lesson.")
    else:
        print(
            "[e2e] DONE — some topics gap-reported (draft, awaiting teacher "
            "design notes + re-generate, per §6)."
        )
    if starved_result is not None:
        print(
            "[e2e] OK — the starved topic failed validation and landed "
            "`draft` with a gap report (acceptance criterion 2)."
        )
    return 0


def _topic_name(supabase: Any, topic_id: str) -> str:
    """Load a topic's `name` for the report."""
    resp = (
        supabase.table("topics")
        .select("name")
        .eq("id", topic_id)
        .single()
        .execute()
    )
    return str((getattr(resp, "data", None) or {}).get("name") or topic_id)


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline.e2e_script",
        description=(
            "End-to-end teacher-pipeline proof on the real Fluids deck "
            "(task 2.7)."
        ),
    )
    parser.add_argument(
        "deck",
        nargs="?",
        default=_DEFAULT_DECK,
        help="path to the unit deck (default: the Unit 8 - Fluids .pptx)",
    )
    parser.add_argument(
        "--max-topics",
        type=int,
        default=None,
        help="generate + validate only the first N proposed topics (default: all)",
    )
    parser.add_argument(
        "--starved-topic",
        action="store_true",
        help=(
            "additionally grade one topic against the whole unit's key "
            "points so it deliberately fails validation with a gap report"
        ),
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(args.deck, args.max_topics, args.starved_topic))


if __name__ == "__main__":
    raise SystemExit(main())
