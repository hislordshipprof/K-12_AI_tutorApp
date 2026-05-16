"""Version-scoped quiz generation (teacher-authoring pipeline, task 2.6).

`teacher-authoring.md` §6 "Quiz": each teacher topic ends with a quiz. Two
sources, the teacher's per-topic choice recorded in `topics.quiz_source`:

  * **auto** (default) — the EXISTING quiz generator
    (`app.content.quiz_generator.QuizGenerator`), run against the topic's
    `comprehension` slice. The same generator Recommended courses use.
  * **practice** — when the unit upload included `practice` material, the
    quiz is built from the teacher's own worksheet questions. The §2.2
    segmentation tagged each practice question to the topic it assesses
    (`unit_segmentations.proposed.practice_tags`).

Quizzes live in the existing separate `quiz_questions` table — so to version
with the lesson, each generate writes a FRESH question set tagged with
`quiz_questions.topic_version_id` = `topics.active_version_id` (§4, already
added by migration `20260515050000`). The live quiz is the set whose
`topic_version_id` = the topic's `active_version_id`; a re-generation (after
a new `generate_topic` version) writes a NEW set under the NEW version and
LEAVES the old rows untouched, so past `quiz_attempts` stay bound to the
version the student actually took.

`quiz_source = 'practice'` is selectable only when the unit has `practice`
material with questions tagged to that topic — otherwise it is rejected
(§6 "the field is forced to 'auto'"). This module's `generate_quiz` raises
`QuizError('no_practice_material')` so the caller can surface the §6 rule.

Scope (Phase 2 is backend-only, proven by a script — `CLAUDE.md`): plain
service functions, NO HTTP endpoints, the `pipeline_jobs` 'generate' job is
NOT wired (consistent with 2.1–2.5). The CORE is decoupled from the DB so it
is data-testable and live-verifiable standalone (`quiz_script.py`).

Public API:
    * ``generate_quiz_set`` — pure-ish core: a topic's data in -> a
      validated `QuizSet` out. Mocked-Gemini testable.
    * ``practice_quiz_set`` — pure core: practice-question rows + tags ->
      a `QuizSet` built from the teacher's own questions.
    * ``generate_quiz``     — DB function: load a topic, its `quiz_source`,
      its `active_version_id`; run the auto or practice path; write fresh
      `quiz_questions` rows tagged to the active version.
    * ``QuizError``         — missing inputs / practice-guard / malformed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.content.chunker import Chunk
from app.content.quiz_generator import QuizGenerator
from app.content.quiz_schema import QuizQuestion, QuizSet
from app.core.logging import get_logger
from app.pipeline.generate import ComprehensionSlice, slice_comprehension
from app.services.gemini import GeminiService

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────
class QuizError(RuntimeError):
    """Quiz generation could not run or produced an unusable result.

    Carries a stable `reason` code so callers branch without string matching:
      * ``no_topic``             — no `topics` row for the given id.
      * ``no_active_version``    — the topic has no `active_version_id`; a
                                   quiz versions with a lesson, so the lesson
                                   must be generated first (task 2.5).
      * ``no_segmentation``      — the topic's unit has no `unit_segmentations`
                                   row, so there is no `comprehension` to
                                   slice for the auto path.
      * ``no_practice_material`` — `quiz_source='practice'` but the unit has
                                   no `practice` material with questions
                                   tagged to this topic (§6 — the choice is
                                   then forced to 'auto' / rejected).
      * ``no_supabase``          — the DB function needs a Supabase client.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Auto path — reuse the EXISTING quiz generator against the comprehension slice.
# ─────────────────────────────────────────────────────────────────────────────
def _slice_to_chunks(slice_: ComprehensionSlice) -> list[Chunk]:
    """Turn a topic's `ComprehensionSlice` into `Chunk`s for the quiz generator.

    The existing `QuizGenerator.generate` takes `source_chunks: list[Chunk]`
    (the OpenStax retrieval passages) and an optional `lesson`. A teacher
    topic has no OpenStax chunks — instead its source is the §2.2
    `comprehension` slice. So each section becomes one `Chunk` (its title +
    key points), and the figure descriptions become a final chunk. The quiz
    generator's prompt already handles "no lesson — fall back to the source
    passages", so passing `lesson=None` + these chunks is the intended path.
    """
    chunks: list[Chunk] = []
    for i, s in enumerate(slice_.sections):
        body = s.title
        if s.key_points:
            body += "\n" + "\n".join(f"- {kp}" for kp in s.key_points)
        chunks.append(Chunk(ordinal=i, text=body, source_url="teacher-material"))
    if slice_.figures:
        figs = "\n".join(f"- {f.description}" for f in slice_.figures)
        chunks.append(
            Chunk(
                ordinal=len(chunks),
                text="Figures:\n" + figs,
                source_url="teacher-material",
            )
        )
    return chunks


async def generate_quiz_set(
    *,
    topic_title: str,
    comprehension_slice: ComprehensionSlice,
    gemini: GeminiService | None = None,
) -> QuizSet:
    """Auto-generate one topic's quiz from its comprehension slice.

    The pure-ish core (no DB): build `Chunk`s from the topic's §2.2
    `comprehension` slice and run the EXISTING `QuizGenerator` — the same
    3-question MCQ generator Recommended courses use. `lesson` is `None`: the
    quiz generator's prompt falls back to the source passages, which here are
    the comprehension slice. Returns a validated `QuizSet`.

    Model: the quiz generator runs on the PRO slot (`settings.gemini_model_pro`,
    `model-strategy.md` §6) — unchanged from the Recommended pipeline.
    """
    chunks = _slice_to_chunks(comprehension_slice)
    log.info("quiz_generate_auto_start", topic=topic_title, chunks=len(chunks))
    quiz = await QuizGenerator(gemini=gemini).generate(
        topic_name=topic_title,
        lesson=None,
        source_chunks=chunks,
    )
    log.info("quiz_generate_auto_ok", topic=topic_title, items=len(quiz.items))
    return quiz


# ─────────────────────────────────────────────────────────────────────────────
# Practice path — build the quiz from the teacher's own worksheet questions.
# ─────────────────────────────────────────────────────────────────────────────
class PracticeQuestion:
    """One practice-worksheet question the teacher tagged to this topic.

    The §2.2 `practice_tags` entry only carries a `question_label` (e.g. 'Q3'
    or a short stem) — the worksheet's full text, choices and answer key are
    NOT in the segmentation. To turn a tagged question into a `quiz_questions`
    row (4 choices + a `correct_idx` + an explanation) we need that detail.

    UNDERSPECIFIED-SPEC NOTE (documented per the task brief): §6 says the
    practice path builds the quiz "from the teacher's practice material" but
    the §4 `practice_tags` shape carries only a label, not a structured MCQ.
    The cleanest minimal choice — and what this dataclass models — is to
    require the practice questions ALREADY be in the `quiz_questions` MCQ
    shape (`prompt` / `choices` / `correct_idx` / `explanation`). The §2.2
    `practice_tags` then act purely as the topic FILTER: they say WHICH
    questions belong to this topic. Re-OCR-ing worksheet pages into MCQs is a
    larger generation problem out of this task's scope; when that capability
    lands it simply produces these structured rows. For task 2.6 the core
    consumes structured practice questions + the tag filter and the guard.
    """

    __slots__ = ("material_idx", "page_idx", "question_label", "question")

    def __init__(
        self,
        *,
        material_idx: int,
        page_idx: int,
        question_label: str,
        question: QuizQuestion,
    ) -> None:
        self.material_idx = material_idx
        self.page_idx = page_idx
        self.question_label = question_label
        self.question = question


def practice_tags_for_topic(
    practice_tags: list[dict[str, Any]],
    topic_idx: int,
) -> list[dict[str, Any]]:
    """Filter a unit's `practice_tags` to the ones assessing `topic_idx`.

    `practice_tags` is `unit_segmentations.proposed.practice_tags` — a list of
    `{material_idx, page_idx, question_label, topic_idx}` (the §2.2
    `PracticeTag` shape). A tag belongs to this topic when its `topic_idx`
    equals the topic's position in the proposed breakdown. `topic_idx == -1`
    means the §2.2 model could not map the question — never this topic.
    """
    return [
        t
        for t in practice_tags
        if isinstance(t, dict) and int(t.get("topic_idx", -1)) == topic_idx
    ]


def practice_quiz_set(questions: list[PracticeQuestion]) -> QuizSet:
    """Build a `QuizSet` from the teacher's own practice questions.

    The pure core of the practice path: the `questions` are already the
    topic's tagged practice questions (filtered by `practice_tags_for_topic`).
    Each is emitted as a `quiz_questions` row unchanged — this path does NOT
    call a model, it surfaces the teacher's real assessment.

    `QuizSet` requires exactly 3 questions (the existing quiz contract). With
    more than 3 tagged questions the first 3 are taken; with fewer than 3 the
    caller should not have selected the practice path — the guard in
    `generate_quiz` rejects that case before this is reached.
    """
    items = [pq.question for pq in questions[:3]]
    return QuizSet(items=items)


# ─────────────────────────────────────────────────────────────────────────────
# DB function — load a topic, run the right path, write version-scoped rows.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class QuizResult:
    """Outcome of `generate_quiz` — the version the quiz was tagged to, the
    `quiz_source` used, and the number of questions written."""

    topic_id: str
    topic_version_id: str
    quiz_source: str  # 'auto' | 'practice'
    question_count: int


def _practice_questions_from_rows(
    rows: list[dict[str, Any]],
) -> list[PracticeQuestion]:
    """Coerce stored practice-question rows into `PracticeQuestion` objects.

    Each row must already carry the MCQ fields (`prompt`/`choices`/
    `correct_idx`/`explanation`) — see `PracticeQuestion`'s spec note. A row
    that fails `QuizQuestion` validation raises `QuizError('malformed')`.
    """
    out: list[PracticeQuestion] = []
    for r in rows:
        try:
            q = QuizQuestion.model_validate(
                {
                    "prompt": r.get("prompt"),
                    "choices": r.get("choices"),
                    "correct_idx": r.get("correct_idx"),
                    "explanation": r.get("explanation"),
                }
            )
        except Exception as e:  # noqa: BLE001 — surface as a stable QuizError
            raise QuizError(
                "malformed",
                f"practice question {r.get('question_label')!r} is not a "
                f"valid MCQ: {e}",
            ) from e
        out.append(
            PracticeQuestion(
                material_idx=int(r.get("material_idx", 0)),
                page_idx=int(r.get("page_idx", 0)),
                question_label=str(r.get("question_label", "")),
                question=q,
            )
        )
    return out


async def generate_quiz(
    topic_id: str,
    *,
    gemini: GeminiService | None = None,
    practice_questions: list[PracticeQuestion] | None = None,
) -> QuizResult:
    """Generate a topic's quiz and persist it tagged to the active version.

    The flow (`teacher-authoring.md` §4, §6 "Quiz"):

      1. Load the `topics` row — its `name`, `quiz_source`,
         `active_version_id`, `unit_id`. Missing -> `QuizError('no_topic')`.
      2. The topic MUST have an `active_version_id` (a quiz versions with a
         lesson — task 2.5 generates the version first). None ->
         `QuizError('no_active_version')`.
      3. Branch on `quiz_source`:
         * ``'practice'`` — the GUARD: the unit must have `practice` material
           with `practice_tags` for THIS topic. The topic's index in the
           latest segmentation's proposed breakdown is matched against the
           tags. No tagged practice questions ->
           `QuizError('no_practice_material')` (§6 — the choice is rejected).
           The quiz is then built from the teacher's own questions.
         * ``'auto'`` (default) — slice the unit's latest `comprehension` for
           this topic and run the existing quiz generator.
      4. Write a FRESH set of `quiz_questions` rows, each with
         `topic_version_id = topics.active_version_id`. A previous version's
         rows (a different `topic_version_id`) are LEFT UNTOUCHED, so the
         `quiz_attempts` taken against them stay valid (§4 / §6).

    Args:
        topic_id: the topic to quiz.
        gemini: a `GeminiService`; constructed lazily if omitted.
        practice_questions: when `quiz_source='practice'`, the topic's
            structured practice questions (see `PracticeQuestion`'s spec
            note). The DB carries only `practice_tags` labels, not full MCQs;
            this argument supplies the structured questions the tags point
            at. Omitted -> the practice path has nothing to build from and
            the guard treats the topic as having no practice material.

    Returns a `QuizResult`. Requires a configured Supabase service-role
    client.
    """
    from app.core.supabase import get_supabase

    supabase = get_supabase()
    if supabase is None:
        raise QuizError(
            "no_supabase",
            "generate_quiz requires Supabase to be configured "
            "(SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)",
        )

    # 1. Load the topic.
    topic_resp = (
        supabase.table("topics")
        .select("id,name,quiz_source,active_version_id,unit_id")
        .eq("id", topic_id)
        .single()
        .execute()
    )
    topic = getattr(topic_resp, "data", None)
    if not topic:
        raise QuizError("no_topic", f"no topics row for id {topic_id}")

    quiz_source = str(topic.get("quiz_source") or "auto")
    topic_version_id = topic.get("active_version_id")
    unit_id = topic.get("unit_id")

    # 2. A quiz versions with a lesson — the active version must exist.
    if not topic_version_id:
        raise QuizError(
            "no_active_version",
            f"topic {topic_id} has no active_version_id — generate the "
            "lesson (task 2.5) before its quiz",
        )

    # 3. Load the unit's latest segmentation (needed by BOTH paths — the auto
    #    path slices its `comprehension`, the practice path reads its
    #    `proposed` topic order to resolve this topic's index).
    seg_resp = (
        supabase.table("unit_segmentations")
        .select("id,comprehension,proposed,created_at")
        .eq("unit_id", unit_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    seg_rows = list(getattr(seg_resp, "data", None) or [])
    if not seg_rows:
        raise QuizError(
            "no_segmentation",
            f"unit {unit_id} has no unit_segmentations — cannot quiz "
            f"topic {topic_id}",
        )
    comprehension = seg_rows[0].get("comprehension") or {}
    proposed = seg_rows[0].get("proposed") or {}

    if quiz_source == "practice":
        quiz = _build_practice_quiz(
            topic=topic,
            proposed=proposed,
            practice_questions=practice_questions,
        )
    else:
        # auto — slice the comprehension for this topic and run the generator.
        claimed = _claimed_pages(supabase, topic_id)
        comprehension_slice = slice_comprehension(comprehension, claimed)
        quiz = await generate_quiz_set(
            topic_title=str(topic.get("name") or ""),
            comprehension_slice=comprehension_slice,
            gemini=gemini,
        )

    # 4. Write a FRESH question set tagged to the active version. The rows of
    #    any OTHER version (different topic_version_id) are NOT touched — old
    #    quiz_attempts stay bound to the version the student took (§4 / §6).
    #    A re-generate of THIS same version replaces only this version's rows.
    supabase.table("quiz_questions").delete().eq(
        "topic_id", topic_id
    ).eq("topic_version_id", topic_version_id).execute()

    provenance = {"source": quiz_source, "topic_version_id": topic_version_id}
    rows = [
        {
            "topic_id": topic_id,
            "topic_version_id": topic_version_id,
            "idx": i,
            "prompt": q.prompt,
            "choices": q.choices,
            "correct_idx": q.correct_idx,
            "explanation": q.explanation,
            "provenance": provenance,
        }
        for i, q in enumerate(quiz.items)
    ]
    supabase.table("quiz_questions").insert(rows).execute()

    log.info(
        "generate_quiz_ok",
        topic_id=topic_id,
        topic_version_id=topic_version_id,
        quiz_source=quiz_source,
        questions=len(rows),
    )
    return QuizResult(
        topic_id=topic_id,
        topic_version_id=str(topic_version_id),
        quiz_source=quiz_source,
        question_count=len(rows),
    )


def _claimed_pages(supabase: Any, topic_id: str) -> list[tuple[int, int]]:
    """Load a topic's claimed `(material_idx, page_idx)` pairs for slicing.

    Mirrors `generate_topic`'s page-loading: each distinct `material_id` is
    mapped to a stable 0-based index so the slice and the §2.2 comprehension
    figure indices agree.
    """
    pages_resp = (
        supabase.table("topic_pages")
        .select("material_id,page_idx")
        .eq("topic_id", topic_id)
        .order("ord")
        .execute()
    )
    page_rows = list(getattr(pages_resp, "data", None) or [])
    material_ids: list[str] = []
    for r in page_rows:
        mid = str(r.get("material_id"))
        if mid not in material_ids:
            material_ids.append(mid)
    return [
        (
            material_ids.index(str(r.get("material_id")))
            if r.get("material_id") is not None
            else 0,
            int(r.get("page_idx") or 0),
        )
        for r in page_rows
    ]


def _build_practice_quiz(
    *,
    topic: dict[str, Any],
    proposed: dict[str, Any],
    practice_questions: list[PracticeQuestion] | None,
) -> QuizSet:
    """The practice path + its guard (§6 — acceptance criterion 3).

    GUARD: `quiz_source='practice'` is valid only when the unit has
    `practice` material with `practice_tags` for THIS topic. Resolution:
      1. The topic's index in the latest segmentation's `proposed.topics`
         (matched on `id` if the proposed topic carries one, else by `title`/
         `name`). An unresolvable topic -> not a practice topic.
      2. The unit's `practice_tags` filtered to that `topic_idx`.
      3. Those tags matched against the supplied structured
         `practice_questions` (by `question_label` + page coordinates).
    If, after all that, fewer than 3 practice questions are available, the
    topic has no usable practice material -> `QuizError('no_practice_material')`
    so the caller surfaces the §6 rule (force to 'auto').
    """
    topic_id = str(topic.get("id"))
    topic_name = str(topic.get("name") or "")
    proposed_topics = list(proposed.get("topics") or [])
    practice_tags = list(proposed.get("practice_tags") or [])

    # 1. Resolve this topic's index in the proposed breakdown.
    topic_idx = -1
    for i, pt in enumerate(proposed_topics):
        if not isinstance(pt, dict):
            continue
        if str(pt.get("id") or "") == topic_id or (
            topic_name and str(pt.get("title") or "") == topic_name
        ):
            topic_idx = i
            break
    if topic_idx < 0:
        raise QuizError(
            "no_practice_material",
            f"topic {topic_id} ({topic_name!r}) could not be located in the "
            "unit's proposed breakdown — cannot resolve its practice tags; "
            "quiz_source 'practice' is not available, use 'auto'",
        )

    # 2. The practice tags assessing this topic.
    tags = practice_tags_for_topic(practice_tags, topic_idx)
    if not tags:
        raise QuizError(
            "no_practice_material",
            f"topic {topic_id} has no practice questions tagged to it "
            "(no 'practice' material covers it); per §6 quiz_source "
            "'practice' is rejected — use 'auto'",
        )

    # 3. Match the tags to the supplied structured practice questions.
    supplied = practice_questions or []
    by_label = {
        (pq.material_idx, pq.page_idx, pq.question_label): pq for pq in supplied
    }
    selected: list[PracticeQuestion] = []
    for t in tags:
        key = (
            int(t.get("material_idx", 0)),
            int(t.get("page_idx", 0)),
            str(t.get("question_label", "")),
        )
        pq = by_label.get(key)
        if pq is not None:
            selected.append(pq)

    if len(selected) < 3:
        raise QuizError(
            "no_practice_material",
            f"topic {topic_id} has only {len(selected)} usable practice "
            "question(s) (need 3); quiz_source 'practice' is rejected — "
            "use 'auto'",
        )
    return practice_quiz_set(selected)


__all__ = [
    "QuizError",
    "PracticeQuestion",
    "QuizResult",
    "generate_quiz_set",
    "practice_quiz_set",
    "practice_tags_for_topic",
    "generate_quiz",
]
