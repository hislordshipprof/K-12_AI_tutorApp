"""Worksheet question extraction — the practice-quiz source (task 2.8).

`teacher-authoring.md` §6 "Quiz": a teacher topic with `quiz_source='practice'`
builds its quiz "from the teacher's practice material" — the worksheet
questions the §2.2 segmentation tagged to that topic. Task 2.6 built the
CONSUMER (`generate_quiz`'s `practice` path / `_build_practice_quiz`): it
matches the topic's `practice_tags` against a supplied `list[PracticeQuestion]`
— structured 4-choice MCQs. But nothing yet turns the teacher's uploaded
worksheet PDF into those structured MCQs, so the practice path is not usable
end to end. This module is that missing producer.

`app.pipeline.quiz.PracticeQuestion`'s own docstring names this task: it says
the `practice_tags` carry only a `question_label`, the worksheet's real text /
choices / answer key are NOT in the segmentation, and "re-OCR-ing worksheet
pages into MCQs is a larger generation problem out of [2.6's] scope; when that
capability lands it simply produces these structured rows." Task 2.8 IS that
capability — it reads the worksheet PDFs and emits exactly those
`PracticeQuestion`s.

What the extraction does, and the load-bearing rule (acceptance criterion 3 —
"flag, don't invent"):

  * For each tagged worksheet question the model produces EITHER a usable
    4-choice MCQ OR a flag. It may emit a `correct_idx` ONLY when the answer
    is determinable FROM THE MATERIAL — a printed answer key, a worked
    solution, or a marked correct option. A bare question with no answer
    anywhere is FLAGGED (`extractable=false`), never guessed or solved.
  * Each emitted MCQ is run through `QuizQuestion.model_validate`; one that
    fails the §-`quiz_schema` constraints (prompt 20–240, 4 distinct choices,
    explanation 20–400) is converted to a `FlaggedQuestion` — the run never
    crashes on one bad question.
  * Every `PracticeQuestion` carries the `(material_idx, page_idx,
    question_label)` triple `_build_practice_quiz` matches tags on, so the
    output is directly consumable by `generate_quiz(topic_id,
    practice_questions=...)`.

Scope (Phase 2 is backend-only, proven by a script — `CLAUDE.md`): plain
service functions, NO HTTP endpoint, NO migration, NO new table. The output is
an in-memory `list[PracticeQuestion]` handed to `generate_quiz` — it is not
persisted by this task. The CORE (`extract_practice_questions`) is decoupled
from the DB and Gemini-mockable; `practice_extract_script.py` is the live
proof.

Model: the extraction call runs on the PRO slot (`settings.gemini_model_pro`,
`model-strategy.md` §6 — quiz-related generation runs on the PRO model).

Public API:
    * ``ExtractError``               — missing inputs / malformed model output.
    * ``FlaggedQuestion``            — a tagged worksheet question that could
      NOT be turned into a usable MCQ, and why.
    * ``PracticeExtractResult``      — the usable `PracticeQuestion`s + the
      `FlaggedQuestion`s of one extraction run.
    * ``extract_practice_questions`` — pure core: worksheet PDFs + practice
      tags in -> a `PracticeExtractResult` out. Mocked-Gemini testable.
    * ``extract_unit_practice``      — DB wrapper: load a unit's latest
      segmentation + its `lesson_materials`, download the worksheet PDFs,
      run the core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.content.quiz_schema import QuizQuestion
from app.core.config import settings
from app.core.logging import get_logger
from app.pipeline.quiz import PracticeQuestion
from app.services.gemini import GeminiService

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────
class ExtractError(RuntimeError):
    """Worksheet extraction could not run or produced an unusable result.

    Carries a stable `reason` code so callers branch without string matching
    (a question that simply cannot be turned into an MCQ is NOT an error — it
    becomes a `FlaggedQuestion`, see "flag, don't invent"):
      * ``no_supabase``       — the DB wrapper needs a Supabase client.
      * ``no_segmentation``   — the unit has no `unit_segmentations` row, so
                                there are no `practice_tags` to extract from.
      * ``no_practice_tags``  — the unit's latest segmentation has zero
                                `practice_tags` (no `practice` material, or no
                                worksheet question was tagged to any topic);
                                there is nothing to extract.
      * ``malformed_output``  — the extraction model returned output that does
                                not parse / validate against the extraction
                                schema; a bad payload is rejected, never used.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Results
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class FlaggedQuestion:
    """A tagged worksheet question that could NOT be turned into a usable MCQ.

    Acceptance criterion 3 ("flag, don't invent"): a question reaches here —
    rather than becoming a `PracticeQuestion` — when the worksheet shows no
    determinable answer (no printed answer key, no worked solution, no marked
    option), when it has more/fewer than 4 options and cannot be cleanly made
    into 4, or when the MCQ the model produced fails `QuizQuestion` validation.

    `material_idx` / `page_idx` / `question_label` identify the worksheet
    question (the §2.2 `practice_tag` coordinates); `reason` is the
    human-readable why, surfaced to the teacher so they can supply the answer
    key or fix the question.
    """

    material_idx: int
    page_idx: int
    question_label: str
    reason: str


@dataclass
class PracticeExtractResult:
    """The outcome of one worksheet-extraction run.

    `questions` are the usable, structured `PracticeQuestion`s — directly
    consumable by `generate_quiz(topic_id, practice_questions=...)`. `flagged`
    are the tagged questions that could NOT be extracted, with the reason.
    Every tagged question the model was asked about lands in exactly one list.
    """

    questions: list[PracticeQuestion] = field(default_factory=list)
    flagged: list[FlaggedQuestion] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Model output shape — the per-question extraction the model emits. These
# Pydantic models double as the Gemini `response_schema`, so structured output
# lands typed; the parse step then enforces the §-`quiz_schema` MCQ contract.
# ─────────────────────────────────────────────────────────────────────────────
class _ExtractedQuestion(BaseModel):
    """The model's read of ONE requested worksheet question.

    `extractable=True` means a usable 4-choice MCQ with an answer DETERMINED
    FROM THE MATERIAL; the MCQ fields are then populated. `extractable=False`
    means the question could not be turned into a usable MCQ — `flag_reason`
    states why and the MCQ fields stay empty (acceptance criterion 3 — the
    model must flag, never guess an answer).
    """

    question_label: str = Field(
        ...,
        description=(
            "Echo the requested practice_tag's question_label VERBATIM so the "
            "result can be matched back to its tag."
        ),
    )
    page_idx: int = Field(
        ..., ge=0, description="0-based page within the worksheet PDF, echoed from the tag"
    )
    extractable: bool = Field(
        ...,
        description=(
            "True only when a usable 4-choice MCQ with an answer determinable "
            "FROM THE MATERIAL was produced; False when the question must be "
            "flagged instead."
        ),
    )
    flag_reason: str | None = Field(
        default=None,
        description=(
            "When extractable is False, a short human-readable reason — e.g. "
            "'no answer key in the material', 'has 5 options, cannot reduce to "
            "4', 'question text is unreadable'."
        ),
    )
    prompt: str | None = Field(
        default=None, description="the MCQ prompt (when extractable)"
    )
    choices: list[str] | None = Field(
        default=None, description="exactly 4 distinct answer choices (when extractable)"
    )
    correct_idx: int | None = Field(
        default=None,
        description=(
            "0-based index of the correct choice (when extractable) — ONLY "
            "from the material's answer key / worked solution / marked option."
        ),
    )
    explanation: str | None = Field(
        default=None,
        description="1-2 sentence explanation of the correct answer (when extractable)",
    )


class _ExtractedWorksheet(BaseModel):
    """The model's full extraction — one `_ExtractedQuestion` per requested tag."""

    questions: list[_ExtractedQuestion] = Field(
        default_factory=list,
        description="one entry per requested (question_label, page_idx), in order",
    )


# ─────────────────────────────────────────────────────────────────────────────
# The extraction prompt — instructs the model to do the "flag, don't invent"
# rule, the MCQ contract, and the per-question echo.
# ─────────────────────────────────────────────────────────────────────────────
EXTRACT_SYSTEM_PROMPT = (
    "You are the worksheet-extraction stage of a teacher-authoring pipeline "
    "for a K-12 tutoring app. A teacher uploaded a PRACTICE worksheet; an "
    "earlier stage tagged specific questions on it to the topics they assess. "
    "Your job is to read the worksheet PDF and turn each requested question "
    "into a usable 4-choice multiple-choice question — OR, when you cannot, "
    "to FLAG it.\n\n"
    "The single most important rule: NEVER invent an answer. You may mark a "
    "correct answer ONLY when the worksheet itself determines it — a printed "
    "answer key, a worked solution, or a visibly marked correct option. If a "
    "question shows only the bare prompt with no answer anywhere in the "
    "material, you MUST flag it (extractable=false) — do not solve it "
    "yourself and do not guess. A flagged question is a correct, honest "
    "outcome; a fabricated answer is a serious error a teacher would have to "
    "catch."
)


def _build_extract_prompt(
    *,
    material_idx: int,
    requests: list[tuple[str, int]],
) -> str:
    """Build the user-slot prompt for ONE material's extraction call.

    `requests` is the list of `(question_label, page_idx)` pairs — the §2.2
    `practice_tags` for this material — that the model must locate in the
    attached worksheet PDF and either extract or flag. The prompt lists them
    explicitly so the model echoes each label/page back and the result can be
    matched to its tag.
    """
    req_lines = [
        f"  • question_label={label!r} on page_idx={page_idx}"
        for label, page_idx in requests
    ]
    return (
        f"This worksheet is material_idx={material_idx} of the unit. Find "
        "EACH of the following tagged questions in the attached worksheet PDF "
        "and return a structured result for it:\n"
        + "\n".join(req_lines)
        + "\n\n"
        "For EACH requested question return one entry, echoing its "
        "`question_label` and `page_idx` verbatim, with EITHER:\n\n"
        "  EXTRACTABLE (`extractable=true`) — a usable multiple-choice "
        "question:\n"
        "    • `prompt` — the question, 20–240 characters, plain prose (math "
        "in $...$).\n"
        "    • `choices` — EXACTLY 4 distinct, non-empty answer choices. If "
        "the worksheet question is already multiple-choice with 4 options, "
        "keep the real options. If it is free-response BUT the material shows "
        "the worked/correct answer, keep that real answer as one choice and "
        "author 3 plausible distractors around it. If it has more or fewer "
        "than 4 options and cannot be cleanly reduced/expanded to 4, do NOT "
        "extract it — flag it instead.\n"
        "    • `correct_idx` — the 0-based index of the correct choice. Set "
        "this ONLY from the worksheet's own answer key / worked solution / "
        "marked option. NEVER solve the question yourself to obtain it.\n"
        "    • `explanation` — 1-2 sentences, 20–400 characters, on why that "
        "answer is correct.\n\n"
        "  FLAGGED (`extractable=false`) — the question canNOT be turned into "
        "a usable, answer-keyed MCQ:\n"
        "    • set `flag_reason` to a short reason — e.g. 'no answer key in "
        "the material', 'has 5 options, cannot reduce to 4', 'question text "
        "is unreadable'.\n"
        "    • leave `prompt`/`choices`/`correct_idx`/`explanation` empty.\n\n"
        "Return structured JSON matching the schema — one entry per requested "
        "question, in the order listed above."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core — extract a unit's tagged worksheet questions into PracticeQuestions.
# ─────────────────────────────────────────────────────────────────────────────
def _group_tags_by_material(
    practice_tags: list[dict[str, Any]],
) -> dict[int, list[tuple[int, str]]]:
    """Group the §2.2 `practice_tags` by `material_idx`.

    Each `practice_tag` is a `{material_idx, page_idx, question_label,
    topic_idx}` dict. The extraction makes ONE `generate_from_pdfs` call per
    material, so the tags are bucketed by `material_idx`; the value is the
    list of `(page_idx, question_label)` pairs to find in that material's PDF.
    A tag with `topic_idx == -1` (the §2.2 model could not map it to a topic)
    is still extracted — the topic FILTER is `generate_quiz`'s job, not this
    module's; here we extract every tagged question.
    """
    by_material: dict[int, list[tuple[int, str]]] = {}
    for t in practice_tags:
        if not isinstance(t, dict):
            continue
        midx = int(t.get("material_idx", 0))
        page_idx = int(t.get("page_idx", 0))
        label = str(t.get("question_label", ""))
        by_material.setdefault(midx, []).append((page_idx, label))
    return by_material


def _parse_worksheet(result: dict[str, Any]) -> _ExtractedWorksheet:
    """Turn a `generate_from_pdfs` result into a validated `_ExtractedWorksheet`.

    Mirrors `segment._parse_segmentation`: accepts either a parsed
    `_ExtractedWorksheet` (structured output) or a JSON dict (the coercion
    fallback). Output that does not validate against the extraction schema
    raises `ExtractError('malformed_output')` — a bad payload is never used.
    """
    payload = result.get("json")
    if isinstance(payload, _ExtractedWorksheet):
        return payload
    if payload is None:
        raise ExtractError(
            "malformed_output",
            "extraction model returned no parseable JSON",
        )
    if not isinstance(payload, dict):
        raise ExtractError(
            "malformed_output",
            f"extraction JSON is a {type(payload).__name__}, expected an object",
        )
    try:
        return _ExtractedWorksheet.model_validate(payload)
    except ValidationError as e:
        raise ExtractError(
            "malformed_output",
            f"extraction output failed schema validation: {e}",
        ) from e


def _convert_question(
    material_idx: int,
    eq: _ExtractedQuestion,
) -> PracticeQuestion | FlaggedQuestion:
    """Turn one `_ExtractedQuestion` into a `PracticeQuestion` or a flag.

    The "flag, don't invent" enforcement (acceptance criterion 3) and the MCQ
    contract enforcement happen here:

      * `extractable=false` -> a `FlaggedQuestion` carrying the model's
        `flag_reason` (the model declined to author an answer — the correct
        outcome for a question with no answer key).
      * `extractable=true` -> the MCQ fields are run through
        `QuizQuestion.model_validate`. On success a `PracticeQuestion` is
        emitted carrying the `(material_idx, page_idx, question_label)` triple
        `generate_quiz`'s `_build_practice_quiz` matches tags on. On a
        validation FAILURE the question is converted to a `FlaggedQuestion`
        whose `reason` is the validation error — the run does NOT crash on one
        bad question.
    """
    if not eq.extractable:
        return FlaggedQuestion(
            material_idx=material_idx,
            page_idx=eq.page_idx,
            question_label=eq.question_label,
            reason=(eq.flag_reason or "").strip()
            or "the extraction model flagged this question without a reason",
        )

    # extractable=True — the MCQ must satisfy the QuizQuestion contract; an
    # MCQ that does not is flagged, not crashed on.
    try:
        question = QuizQuestion.model_validate(
            {
                "prompt": eq.prompt,
                "choices": eq.choices,
                "correct_idx": eq.correct_idx,
                "explanation": eq.explanation,
            }
        )
    except ValidationError as e:
        return FlaggedQuestion(
            material_idx=material_idx,
            page_idx=eq.page_idx,
            question_label=eq.question_label,
            reason=f"extracted MCQ failed quiz-schema validation: {e}",
        )

    return PracticeQuestion(
        material_idx=material_idx,
        page_idx=eq.page_idx,
        question_label=eq.question_label,
        question=question,
    )


async def extract_practice_questions(
    *,
    pdfs_by_material: dict[int, bytes],
    practice_tags: list[dict[str, Any]],
    gemini: GeminiService | None = None,
) -> PracticeExtractResult:
    """Extract a unit's tagged worksheet questions into structured MCQs.

    The pure core (no DB): the §2.2 `practice_tags` are grouped by
    `material_idx`; for each material that has tags ONE `generate_from_pdfs`
    call is made — that material's worksheet PDF plus a prompt listing the
    `(question_label, page_idx)` pairs to find — with the `_ExtractedWorksheet`
    Pydantic `response_schema`. Each returned question is converted to either a
    usable `PracticeQuestion` or a `FlaggedQuestion` (`_convert_question`):

      * a question the model flagged (`extractable=false` — e.g. no answer key
        in the material) becomes a `FlaggedQuestion` — acceptance criterion 3,
        "flag, don't invent";
      * an `extractable=true` MCQ that fails `QuizQuestion` validation also
        becomes a `FlaggedQuestion` — the run never crashes on one bad item;
      * a valid one becomes a `PracticeQuestion` carrying the
        `(material_idx, page_idx, question_label)` triple `generate_quiz`'s
        `_build_practice_quiz` matches tags on.

    Args:
        pdfs_by_material: the worksheet PDF bytes keyed by `material_idx` — the
            0-based index a `practice_tag` references. A material with tags but
            no PDF here has every one of its tagged questions flagged.
        practice_tags: the unit's `unit_segmentations.proposed.practice_tags`
            — `{material_idx, page_idx, question_label, topic_idx}` dicts. The
            full list is extracted; the per-topic filter is `generate_quiz`'s
            job. `topic_idx` is not consulted here.
        gemini: a `GeminiService`; constructed lazily if omitted (tests inject
            a stub).

    Model: the extraction call runs on the PRO slot (`settings.gemini_model_pro`,
    `model-strategy.md` §6 — quiz-related generation runs on the PRO model).

    Returns a `PracticeExtractResult`. Raises `ExtractError('malformed_output')`
    if a material's extraction response cannot be parsed.
    """
    svc = gemini or GeminiService()
    by_material = _group_tags_by_material(practice_tags)

    questions: list[PracticeQuestion] = []
    flagged: list[FlaggedQuestion] = []

    log.info(
        "practice_extract_start",
        materials=len(by_material),
        tags=len(practice_tags),
        model=settings.gemini_model_pro,
    )

    for material_idx in sorted(by_material):
        requests = by_material[material_idx]
        pdf = pdfs_by_material.get(material_idx)
        if pdf is None:
            # A material was tagged but its PDF was not supplied — every one of
            # its tagged questions is flagged rather than dropped silently.
            for page_idx, label in requests:
                flagged.append(
                    FlaggedQuestion(
                        material_idx=material_idx,
                        page_idx=page_idx,
                        question_label=label,
                        reason="worksheet PDF for this material was not available",
                    )
                )
            log.warning(
                "practice_extract_missing_pdf",
                material_idx=material_idx,
                tags=len(requests),
            )
            continue

        prompt = _build_extract_prompt(material_idx=material_idx, requests=requests)
        result = await svc.generate_from_pdfs(
            [pdf],
            prompt,
            system=EXTRACT_SYSTEM_PROMPT,
            model=settings.gemini_model_pro,
            response_schema=_ExtractedWorksheet,
        )
        worksheet = _parse_worksheet(result)

        for eq in worksheet.questions:
            converted = _convert_question(material_idx, eq)
            if isinstance(converted, PracticeQuestion):
                questions.append(converted)
            else:
                flagged.append(converted)

    log.info(
        "practice_extract_ok",
        extracted=len(questions),
        flagged=len(flagged),
    )
    return PracticeExtractResult(questions=questions, flagged=flagged)


# ─────────────────────────────────────────────────────────────────────────────
# DB wrapper — load a unit's segmentation + worksheet PDFs, run the core.
# ─────────────────────────────────────────────────────────────────────────────
async def extract_unit_practice(
    unit_id: str,
    *,
    gemini: GeminiService | None = None,
) -> PracticeExtractResult:
    """Extract a unit's tagged worksheet questions, loading everything from DB.

    The flow (`teacher-authoring.md` §6, §2.2):

      1. Load the unit's LATEST `unit_segmentations` row. None ->
         `ExtractError('no_segmentation')`. Its `proposed.practice_tags` are
         the worksheet questions to extract; an empty list ->
         `ExtractError('no_practice_tags')` (the unit has no `practice`
         material, or none was tagged — there is nothing to extract).
      2. Load the unit's `lesson_materials` ordered by `uploaded_at` — the
         IDENTICAL ordering `segment_unit` used, so the 0-based position
         aligns with `practice_tags.material_idx`.
      3. Download the `normalized_pdf` of each material that actually has tags
         from the `lesson-materials` Storage bucket via the service-role
         client (mirrors `segment_unit`'s Storage download).
      4. Run `extract_practice_questions` — one PRO-model call per worksheet.

    The result's `questions` are an in-memory `list[PracticeQuestion]` ready
    to hand to `generate_quiz(topic_id, practice_questions=...)`; per the
    Phase-2 scope this task does NOT persist them.

    Args:
        unit_id: the unit whose worksheet questions are being extracted.
        gemini: a `GeminiService`; constructed lazily if omitted.

    Returns a `PracticeExtractResult`. Requires a configured Supabase
    service-role client (reads `unit_segmentations` + `lesson_materials`,
    reads Storage).
    """
    from app.core.supabase import get_supabase

    supabase = get_supabase()
    if supabase is None:
        raise ExtractError(
            "no_supabase",
            "extract_unit_practice requires Supabase to be configured "
            "(SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)",
        )

    # 1. The unit's latest segmentation — its proposed.practice_tags.
    seg_resp = (
        supabase.table("unit_segmentations")
        .select("id,proposed,created_at")
        .eq("unit_id", unit_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    seg_rows = list(getattr(seg_resp, "data", None) or [])
    if not seg_rows:
        raise ExtractError(
            "no_segmentation",
            f"unit {unit_id} has no unit_segmentations — segment it first",
        )
    proposed = seg_rows[0].get("proposed") or {}
    practice_tags = [
        t for t in (proposed.get("practice_tags") or []) if isinstance(t, dict)
    ]
    if not practice_tags:
        raise ExtractError(
            "no_practice_tags",
            f"unit {unit_id}'s latest segmentation has no practice_tags — the "
            "unit has no 'practice' material with questions tagged to a topic; "
            "there is nothing to extract",
        )

    # 2. The unit's materials, in the SAME order segment_unit used (uploaded_at)
    #    — so the 0-based index aligns with practice_tags.material_idx.
    mat_resp = (
        supabase.table("lesson_materials")
        .select("id,filename,normalized_pdf,uploaded_at")
        .eq("unit_id", unit_id)
        .order("uploaded_at")
        .execute()
    )
    material_rows = list(getattr(mat_resp, "data", None) or [])

    # 3. Download the normalized PDF of each material that actually has tags.
    needed = {int(t.get("material_idx", 0)) for t in practice_tags}
    bucket = supabase.storage.from_("lesson-materials")
    pdfs_by_material: dict[int, bytes] = {}
    for idx, row in enumerate(material_rows):
        if idx not in needed:
            continue
        key = row.get("normalized_pdf")
        if not key:
            # A tagged material with no converted PDF — leave it out of the
            # map; the core flags its tagged questions rather than crashing.
            log.warning(
                "practice_extract_material_no_pdf",
                unit_id=unit_id,
                material_idx=idx,
            )
            continue
        pdfs_by_material[idx] = bucket.download(key)

    # 4. Run the core extraction.
    result = await extract_practice_questions(
        pdfs_by_material=pdfs_by_material,
        practice_tags=practice_tags,
        gemini=gemini,
    )
    log.info(
        "extract_unit_practice_done",
        unit_id=unit_id,
        extracted=len(result.questions),
        flagged=len(result.flagged),
    )
    return result


__all__ = [
    "ExtractError",
    "FlaggedQuestion",
    "PracticeExtractResult",
    "EXTRACT_SYSTEM_PROMPT",
    "extract_practice_questions",
    "extract_unit_practice",
]
