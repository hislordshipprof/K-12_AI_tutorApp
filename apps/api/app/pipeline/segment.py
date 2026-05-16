"""Comprehension + topic segmentation (teacher-authoring pipeline, task 2.2).

`teacher-authoring.md` §6 "Comprehend + segment (model track)": every file a
teacher uploaded for a unit is combined into ONE multimodal Gemini request.
The model reads the whole document — prose, tables, equations, figures,
scanned/messy pages — and writes a `unit_segmentations` row:

  * ``comprehension`` — its combined read: per-material kind, per-section key
    points, per-figure descriptions, and a per-page teach/skip classification.
  * ``proposed`` — a proposed topic breakdown: a list of distinct topics,
    each with a title, a summary, and the *set* of pages that cover it
    (material-aware, possibly non-contiguous, possibly spanning materials),
    plus practice-question -> topic tags.

This is the single highest-stakes call in the pipeline — it sets the topic
tree the teacher then confirms (§5.7). It runs on a STRONGER model than the
per-step work (`model-strategy.md` §6): `gemini-3-flash-preview`, escalating
to `gemini-3.1-pro-preview` for a large/messy deck, with chunking above a
page threshold.

Scope (Phase 2 is backend-only, proven by a script — `CLAUDE.md`): this
module is plain service functions. There are no HTTP endpoints here and the
`pipeline_jobs` 'segment' job is NOT wired — that orchestration comes later,
consistent with how 2.1 was scoped. `segment_script.py` exercises it.

Public API:
    * ``comprehend_unit``   — pure-ish core: PDFs in -> validated
      ``UnitSegmentation`` out. Mocked-Gemini testable.
    * ``segment_unit``      — DB function: load a unit's converted
      `lesson_materials`, run the core, INSERT a `unit_segmentations` row
      (``status='proposed'``).
    * ``SegmentError``      — converted-materials guard / malformed-output.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.core.logging import get_logger
from app.services.gemini import GeminiService

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────
class SegmentError(RuntimeError):
    """Segmentation could not run or produced an unusable result.

    Carries a stable `reason` code so callers branch without string matching:
      * ``no_materials``        — the unit has no `lesson_materials` rows.
      * ``not_converted``       — a material is not yet `conversion_status
                                  ='converted'` (§13 — segment needs PDFs).
      * ``malformed_output``    — the model returned output that does not
                                  validate against the §4 schema; the bad
                                  row is rejected, never written.
      * ``no_supabase``         — the DB function needs a Supabase client.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# §4 `unit_segmentations` shape — the concrete schema for `comprehension` +
# `proposed`. These Pydantic models are ALSO the Gemini `response_schema`, so
# structured output lands typed; validation then rejects malformed model
# output before it can be written to the row.
# ─────────────────────────────────────────────────────────────────────────────
class PageClass(BaseModel):
    """Per-page teach/skip classification — one entry per page of one material.

    `material_idx` indexes into the unit's material list (the order the PDFs
    were handed to the model); `page_idx` is the 0-based page within that
    material. `teach=False` marks a non-teaching page (title / agenda /
    "any questions?" / reference) that must never become a topic.
    """

    material_idx: int = Field(..., ge=0, description="index into the unit's material list")
    page_idx: int = Field(..., ge=0, description="0-based page within that material")
    teach: bool = Field(..., description="True = a teaching page; False = excluded")
    reason: str = Field(
        ...,
        description=(
            "Short why — for a skipped page the kind of non-teaching page it "
            "is (title/agenda/questions/reference); for a kept page, blank or "
            "a one-line note. Also names a page dropped as a duplicate "
            "animation-build frame."
        ),
    )


class FigureDesc(BaseModel):
    """One figure/diagram the model found, with a plain-language description."""

    material_idx: int = Field(..., ge=0)
    page_idx: int = Field(..., ge=0)
    description: str = Field(..., description="what the figure shows")


class SectionRead(BaseModel):
    """The model's read of one coherent section of the combined document."""

    title: str = Field(..., description="the section's heading or a short label")
    key_points: list[str] = Field(
        default_factory=list, description="the teachable points of this section"
    )
    too_thin: bool = Field(
        default=False,
        description=(
            "True when the section is too sparse to teach on its own — flagged "
            "rather than spun into a hollow topic (§13 thin-material rule)."
        ),
    )
    duplicate_of: str | None = Field(
        default=None,
        description=(
            "Set to an earlier section's title when this section is a recap / "
            "review repeating it — flags the near-duplicate so it does NOT "
            "spawn a second topic (§13 recap rule)."
        ),
    )


class MaterialRead(BaseModel):
    """The model's per-material classification — its kind and page count."""

    material_idx: int = Field(..., ge=0)
    kind: str = Field(
        ...,
        description="'notes' | 'slides' | 'practice' — the model's classification",
    )
    page_count: int = Field(..., ge=0)


class Comprehension(BaseModel):
    """`unit_segmentations.comprehension` — the combined multimodal read."""

    materials: list[MaterialRead] = Field(default_factory=list)
    sections: list[SectionRead] = Field(default_factory=list)
    figures: list[FigureDesc] = Field(default_factory=list)
    pages: list[PageClass] = Field(
        default_factory=list,
        description="per-page teach/skip classification across all materials",
    )


class PageRef(BaseModel):
    """One page of one material — an element of a topic's page SET.

    A topic's page set is a list of these: it may be non-contiguous and may
    span materials (§13 non-contiguous coverage; slides + a notes doc). It is
    material-aware because `topic_pages` is keyed by (topic, material, page).
    """

    material_idx: int = Field(..., ge=0)
    page_idx: int = Field(..., ge=0)


class PracticeTag(BaseModel):
    """A practice question tagged with the topic it assesses (§6 / §13).

    `topic_idx` indexes into `ProposedBreakdown.topics`; -1 means the question
    could not be confidently mapped to any proposed topic.
    """

    material_idx: int = Field(..., ge=0)
    page_idx: int = Field(..., ge=0)
    question_label: str = Field(..., description="e.g. 'Q3' or a short stem")
    topic_idx: int = Field(..., ge=-1, description="index into topics; -1 = unmapped")


class ProposedTopic(BaseModel):
    """One proposed topic — title, summary, and its page set."""

    title: str = Field(..., description="a concise topic title")
    summary: str = Field(..., description="2-3 sentences on what the topic covers")
    pages: list[PageRef] = Field(
        default_factory=list,
        description="the SET of pages that cover this topic (slides/figures)",
    )


class ProposedBreakdown(BaseModel):
    """`unit_segmentations.proposed` — the proposed topic breakdown."""

    topics: list[ProposedTopic] = Field(default_factory=list)
    practice_tags: list[PracticeTag] = Field(
        default_factory=list,
        description="practice questions tagged to the topic they assess",
    )
    empty_reason: str | None = Field(
        default=None,
        description=(
            "When the upload has no teachable content (§13), `topics` is empty "
            "and this states why — 'nothing teachable found here', not invented "
            "topics."
        ),
    )


class UnitSegmentation(BaseModel):
    """The full model output — the `comprehension` + `proposed` of one row."""

    comprehension: Comprehension
    proposed: ProposedBreakdown


# ─────────────────────────────────────────────────────────────────────────────
# The comprehension prompt — instructs the model to do every §13 case.
# ─────────────────────────────────────────────────────────────────────────────
COMPREHENSION_SYSTEM_PROMPT = (
    "You are the comprehension stage of a teacher-authoring pipeline for a "
    "K-12 tutoring app. A teacher has uploaded the raw material for ONE unit "
    "of a course — notes, slide decks, worksheets, in any order and any "
    "quality (clean or messy, typed or scanned, with equations and figures). "
    "Your job is to READ the whole combined document and STRUCTURE it: "
    "classify every page, summarise every section, and propose a breakdown "
    "into distinct teachable topics.\n\n"
    "You only ever PROPOSE. A human teacher reviews and edits your breakdown "
    "afterwards, so be accurate and conservative — never invent content that "
    "is not in the upload."
)


def _build_comprehension_prompt(materials: list[dict[str, Any]]) -> str:
    """Build the user-slot prompt — lists the materials and the §13 rules.

    `materials` is the ordered list handed to the model; each dict carries at
    least `filename` and `kind` (the teacher's claimed kind, which the model
    may correct). The PDFs themselves are attached as separate inline parts —
    this text just tells the model the order and what to do.
    """
    lines = [
        "The unit's materials, in the order their PDFs are attached below "
        "(material_idx is this 0-based position):",
    ]
    for i, m in enumerate(materials):
        lines.append(
            f"  [material_idx={i}] filename={m.get('filename', '?')!r} "
            f"teacher_claimed_kind={m.get('kind', 'notes')!r}"
        )
    rules = """
READ all the attached PDFs as ONE combined document and return STRUCTURED
JSON matching the schema. Apply every rule below.

PER-MATERIAL KIND. For each material classify `kind` as one of:
  • 'slides'   — a presentation deck (one idea per page, visual).
  • 'notes'    — prose / textbook-style notes.
  • 'practice' — a worksheet or problem set of questions to be answered.
The teacher's claimed kind is a hint only — correct it if the content
disagrees.

PER-PAGE TEACH / SKIP. Classify EVERY page of EVERY material in `pages`.
  • Non-teaching pages — a title page, an agenda / outline, an "any
    questions?" / "thank you" slide, a references / bibliography page —
    set `teach=false` and name the kind in `reason`. They must NEVER
    become a topic.
  • Real teaching pages — set `teach=true`.

ANIMATION-BUILD COLLAPSE. Authors fake PowerPoint animations by DUPLICATING
a slide and adding one element per copy — a run of consecutive slides with
the SAME title and progressively more content (e.g. slides 6, 7, 8 all
titled "Solid"; slides 14, 15, 16 all "Density"). These are ONE teaching
beat, not three. Collapse such a run: keep ONLY the FINAL, most-complete
slide as a teaching page (`teach=true`); set the earlier partial frames
`teach=false` with `reason` naming them as duplicate animation-build
frames. The same applies to true slide transitions. Only the final slide
of a run goes into a topic's page set.

RECAP / REVIEW. A slide or section that recaps or reviews content already
taught earlier must NOT spawn a second topic. In `sections`, set that
section's `duplicate_of` to the earlier section's title so the recap is
flagged, not turned into a duplicate topic.

THIN MATERIAL. If a section is too sparse to teach honestly (a few bullet
words, no real substance), set its `too_thin=true` rather than proposing a
hollow, hallucination-prone topic for it.

PRACTICE MATERIAL. Pages of a 'practice' material are questions, never a
lesson — keep them `teach=true` only in the sense that they are real
content, but DO NOT create a topic from them. Instead, in `practice_tags`,
tag each practice question with the `topic_idx` of the proposed topic it
assesses (use -1 if it maps to none).

PROPOSED TOPICS. Propose a list of DISTINCT teachable topics. Each topic
has a title, a 2-3 sentence summary, and a `pages` SET — the pages that
cover it. A topic's page set:
  • may be NON-CONTIGUOUS (covers concept A, then B, then back to A);
  • may SPAN materials (slide pages + notes pages for the same idea);
  • contains only `slides`/figure pages — never prose `notes` or
    `practice` pages (those are read for depth but not displayed);
  • for a collapsed animation-build run, contains only the FINAL slide.

EMPTY UPLOAD. If the upload has NO teachable content at all (a grade
spreadsheet, a permission slip, an agenda-only deck), return an EMPTY
`topics` list and set `empty_reason` explaining why. DO NOT invent topics.
""".strip()
    return "\n".join(lines) + "\n\n" + rules


# ─────────────────────────────────────────────────────────────────────────────
# Model selection — escalate / chunk on combined payload size (§13).
# ─────────────────────────────────────────────────────────────────────────────
def _pdf_page_count(pdf: bytes) -> int:
    """Best-effort page count of a PDF — counts `/Type /Page` objects.

    A cheap, dependency-free heuristic (the project rule: don't add a library
    a task does not need — `pymupdf` arrives in 2.3 for rendering). It only
    drives the escalate/chunk *threshold*, so an approximate count is fine.
    """
    # `/Type /Page` (not `/Pages`) marks each page object; tolerate whitespace.
    import re

    return len(re.findall(rb"/Type\s*/Page[^s]", pdf)) or 1


def choose_segment_model(total_pages: int) -> str:
    """Pick the comprehension model for a combined deck of `total_pages`.

    Default `gemini-3-flash-preview`; escalate to the pinned PRO model once
    the combined page count crosses `settings.segment_escalate_pages`
    (`model-strategy.md` §6 — "escalating to gemini-3.1-pro-preview for
    large/messy decks"). The threshold is a config knob, tuned empirically.
    """
    if total_pages >= settings.segment_escalate_pages:
        return settings.gemini_model_pro
    return settings.gemini_model_segment


# ─────────────────────────────────────────────────────────────────────────────
# Core — comprehend a unit's PDFs into a validated UnitSegmentation.
# ─────────────────────────────────────────────────────────────────────────────
async def comprehend_unit(
    pdfs: list[bytes],
    materials: list[dict[str, Any]],
    *,
    gemini: GeminiService | None = None,
) -> UnitSegmentation:
    """Comprehend a unit's normalized PDFs into a validated `UnitSegmentation`.

    The pure-ish core (no DB): build ONE combined multimodal request from all
    the unit's PDFs, call the comprehension model, and parse + VALIDATE the
    response against the §4 schema. Malformed model output is REJECTED with
    `SegmentError('malformed_output')` — a bad row is never returned.

    Args:
        pdfs: the unit's normalized PDF bytes, in material order.
        materials: per-material metadata (`filename`, `kind`), same order as
            `pdfs` — used to build the prompt and the page index.
        gemini: a `GeminiService`; constructed lazily if omitted (tests
            inject a stub).

    Model selection (§13): page count drives escalation to PRO and, above a
    larger threshold, chunking the combined payload and merging the proposed
    breakdowns. Chunking keeps it simple — it splits the materials into
    page-bounded groups, comprehends each, and concatenates the results.
    """
    if not pdfs:
        raise SegmentError("no_materials", "comprehend_unit needs at least one PDF")
    if len(pdfs) != len(materials):
        raise SegmentError(
            "malformed_output",
            f"pdfs ({len(pdfs)}) and materials ({len(materials)}) must align",
        )

    svc = gemini or GeminiService()

    page_counts = [_pdf_page_count(p) for p in pdfs]
    total_pages = sum(page_counts)

    # Very large deck (§13): chunk the combined payload and merge breakdowns.
    if total_pages > settings.segment_chunk_pages and len(pdfs) > 1:
        return await _comprehend_chunked(pdfs, materials, page_counts, svc)

    model = choose_segment_model(total_pages)
    prompt = _build_comprehension_prompt(materials)

    log.info(
        "segment_comprehend_start",
        materials=len(pdfs),
        total_pages=total_pages,
        model=model,
    )
    result = await svc.generate_from_pdfs(
        pdfs,
        prompt,
        system=COMPREHENSION_SYSTEM_PROMPT,
        model=model,
        response_schema=UnitSegmentation,
    )
    seg = _parse_segmentation(result)
    log.info(
        "segment_comprehend_ok",
        topics=len(seg.proposed.topics),
        empty=seg.proposed.empty_reason is not None,
    )
    return seg


def _parse_segmentation(result: dict[str, Any]) -> UnitSegmentation:
    """Turn a `generate_from_pdfs` result into a validated `UnitSegmentation`.

    Rejects malformed model output — anything that does not validate against
    the §4 schema raises `SegmentError('malformed_output')` so a bad row is
    never persisted. Accepts either a parsed `UnitSegmentation` (structured
    output) or a JSON dict (the coercion fallback).
    """
    payload = result.get("json")
    if isinstance(payload, UnitSegmentation):
        return payload
    if payload is None:
        raise SegmentError(
            "malformed_output",
            "comprehension model returned no parseable JSON",
        )
    if not isinstance(payload, dict):
        raise SegmentError(
            "malformed_output",
            f"comprehension JSON is a {type(payload).__name__}, expected an object",
        )
    try:
        return UnitSegmentation.model_validate(payload)
    except ValidationError as e:
        raise SegmentError(
            "malformed_output",
            f"comprehension output failed §4 schema validation: {e}",
        ) from e


async def _comprehend_chunked(
    pdfs: list[bytes],
    materials: list[dict[str, Any]],
    page_counts: list[int],
    svc: GeminiService,
) -> UnitSegmentation:
    """Chunk a very large unit, comprehend each chunk, merge the breakdowns.

    §13 "very large unit deck": the ceiling is combined-payload tokens, not
    page count — above `segment_chunk_pages` the materials are split into
    page-bounded chunks, each comprehended on its own, and the proposed
    breakdowns are concatenated. Material indices are kept GLOBAL (offset by
    the chunk's starting material) so page sets stay addressable.
    """
    chunks: list[tuple[int, list[bytes], list[dict[str, Any]]]] = []
    cur_pdfs: list[bytes] = []
    cur_mats: list[dict[str, Any]] = []
    cur_pages = 0
    start_idx = 0
    for i, pdf in enumerate(pdfs):
        if cur_pdfs and cur_pages + page_counts[i] > settings.segment_chunk_pages:
            chunks.append((start_idx, cur_pdfs, cur_mats))
            start_idx = i
            cur_pdfs, cur_mats, cur_pages = [], [], 0
        cur_pdfs.append(pdf)
        cur_mats.append(materials[i])
        cur_pages += page_counts[i]
    if cur_pdfs:
        chunks.append((start_idx, cur_pdfs, cur_mats))

    log.info("segment_comprehend_chunked", chunks=len(chunks), materials=len(pdfs))

    merged_materials: list[MaterialRead] = []
    merged_sections: list[SectionRead] = []
    merged_figures: list[FigureDesc] = []
    merged_pages: list[PageClass] = []
    merged_topics: list[ProposedTopic] = []
    merged_tags: list[PracticeTag] = []

    for offset, c_pdfs, c_mats in chunks:
        prompt = _build_comprehension_prompt(c_mats)
        result = await svc.generate_from_pdfs(
            c_pdfs,
            prompt,
            system=COMPREHENSION_SYSTEM_PROMPT,
            model=settings.gemini_model_pro,  # a deck this large always uses PRO
            response_schema=UnitSegmentation,
        )
        seg = _parse_segmentation(result)
        topic_base = len(merged_topics)
        # Re-base every chunk-local material index to a global one.
        for m in seg.comprehension.materials:
            m.material_idx += offset
            merged_materials.append(m)
        merged_sections.extend(seg.comprehension.sections)
        for f in seg.comprehension.figures:
            f.material_idx += offset
            merged_figures.append(f)
        for p in seg.comprehension.pages:
            p.material_idx += offset
            merged_pages.append(p)
        for t in seg.proposed.topics:
            for pr in t.pages:
                pr.material_idx += offset
            merged_topics.append(t)
        for tag in seg.proposed.practice_tags:
            tag.material_idx += offset
            tag.topic_idx = tag.topic_idx + topic_base if tag.topic_idx >= 0 else -1
            merged_tags.append(tag)

    return UnitSegmentation(
        comprehension=Comprehension(
            materials=merged_materials,
            sections=merged_sections,
            figures=merged_figures,
            pages=merged_pages,
        ),
        proposed=ProposedBreakdown(
            topics=merged_topics,
            practice_tags=merged_tags,
            empty_reason=None if merged_topics else "no teachable content found",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# DB function — load a unit's materials, comprehend, write the row.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SegmentResult:
    """Outcome of `segment_unit` — the persisted `unit_segmentations` row id
    and a count of the topics the model proposed."""

    segmentation_id: str
    unit_id: str
    status: str  # always 'proposed' for this task
    topic_count: int
    empty_reason: str | None = None


async def segment_unit(
    unit_id: str,
    *,
    gemini: GeminiService | None = None,
) -> SegmentResult:
    """Comprehend a unit's uploads and append a `unit_segmentations` row.

    The flow (`teacher-authoring.md` §6, §13):

      1. Load the unit's `lesson_materials` rows. With NONE, raise
         `SegmentError('no_materials')`.
      2. Guard — EVERY material must be `conversion_status='converted'`
         (§13 "segment called before materials finish converting"). A
         pending / failed material raises `SegmentError('not_converted')`.
      3. Download each `normalized_pdf` from the `lesson-materials` Storage
         bucket via the service-role client.
      4. Run `comprehend_unit` — the combined multimodal call + validation.
      5. INSERT a `unit_segmentations` row with `status='proposed'`. A
         re-segment appends a NEW row; the latest drives the confirm UI.

    Returns a `SegmentResult`. Requires a configured Supabase service-role
    client (reads `lesson_materials`, reads Storage, writes
    `unit_segmentations`).
    """
    from app.core.supabase import get_supabase

    supabase = get_supabase()
    if supabase is None:
        raise SegmentError(
            "no_supabase",
            "segment_unit requires Supabase to be configured "
            "(SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)",
        )

    # 1. Load the unit's materials, in a stable order.
    resp = (
        supabase.table("lesson_materials")
        .select("id,kind,filename,normalized_pdf,conversion_status,uploaded_at")
        .eq("unit_id", unit_id)
        .order("uploaded_at")
        .execute()
    )
    rows: list[dict[str, Any]] = list(getattr(resp, "data", None) or [])
    if not rows:
        raise SegmentError(
            "no_materials",
            f"unit {unit_id} has no lesson_materials to segment",
        )

    # 2. Guard — every material must have finished converting (§13).
    not_converted = [
        r for r in rows if r.get("conversion_status") != "converted"
    ]
    if not_converted:
        names = ", ".join(
            f"{r.get('filename', '?')}={r.get('conversion_status')}"
            for r in not_converted
        )
        raise SegmentError(
            "not_converted",
            f"unit {unit_id} has materials not yet converted: {names}",
        )

    # 3. Download each normalized PDF from Storage.
    bucket = supabase.storage.from_("lesson-materials")
    pdfs: list[bytes] = []
    materials: list[dict[str, Any]] = []
    for r in rows:
        key = r.get("normalized_pdf")
        if not key:
            raise SegmentError(
                "not_converted",
                f"material {r.get('id')} is 'converted' but has no normalized_pdf",
            )
        pdfs.append(bucket.download(key))
        materials.append({"filename": r.get("filename"), "kind": r.get("kind")})

    # 4. Comprehend + segment — the multimodal call, validated.
    seg = await comprehend_unit(pdfs, materials, gemini=gemini)

    # 5. Append the unit_segmentations row (status='proposed').
    seg_id = str(uuid.uuid4())
    now = _dt.datetime.now(_dt.UTC).isoformat()
    supabase.table("unit_segmentations").insert(
        {
            "id": seg_id,
            "unit_id": unit_id,
            "comprehension": seg.comprehension.model_dump(),
            "proposed": seg.proposed.model_dump(),
            "status": "proposed",
            "created_at": now,
        }
    ).execute()

    log.info(
        "segment_unit_ok",
        unit_id=unit_id,
        segmentation_id=seg_id,
        topics=len(seg.proposed.topics),
    )
    return SegmentResult(
        segmentation_id=seg_id,
        unit_id=unit_id,
        status="proposed",
        topic_count=len(seg.proposed.topics),
        empty_reason=seg.proposed.empty_reason,
    )


__all__ = [
    "SegmentError",
    "PageClass",
    "FigureDesc",
    "SectionRead",
    "MaterialRead",
    "Comprehension",
    "PageRef",
    "PracticeTag",
    "ProposedTopic",
    "ProposedBreakdown",
    "UnitSegmentation",
    "COMPREHENSION_SYSTEM_PROMPT",
    "choose_segment_model",
    "comprehend_unit",
    "segment_unit",
    "SegmentResult",
]
