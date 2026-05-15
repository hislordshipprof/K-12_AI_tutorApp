"""Content pipeline CLI.

Subcommands:
  ingest --topic-slug <slug>     pull source → chunk → embed → upsert chunks
  generate --topic-slug <slug>   generate + validate + persist 8-step lesson
                                 (B2 — uses chunks already in Supabase)
  verify  [--topic-slug | --course | --all]
                                 sanity-check what's in Supabase

Run:
    python -m app.content.cli ingest   --topic-slug ap-physics-1.unit-7.oscillations
    python -m app.content.cli generate --topic-slug ap-physics-1.unit-7.oscillations
    python -m app.content.cli verify --all

The CLI is intentionally a thin orchestration layer — the real work lives in
extractors / chunker / embedder / generator / validator / persister.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any

from app.content.chunker import Chunk, chunk_section
from app.content.embedder import get_embedder
from app.content.extractors import Section, extract_section
from app.content.generator import LessonGenerator
from app.content.persister import (
    HumanReviewedConflict,
    LessonPersister,
    compute_provenance_hash,
)
from app.content.schema import LessonContent
from app.content.sources import SectionRef, parse_topic_slug, resolve_topic
from app.content.validator import VALIDATOR_VERSION, ValidationReport, validate
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

API_ROOT = Path(__file__).resolve().parents[2]  # apps/api/
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _reconfigure_stdout() -> None:
    """UTF-8 stdout so unicode math (π √ ω) renders on Windows consoles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _load_env() -> None:
    """Best-effort .env loader. App-side config also reads it, but the CLI is
    run outside the FastAPI lifespan so we hydrate explicitly."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = API_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _resolve_topic_in_supabase(topic_slug: str) -> dict[str, Any] | None:
    """Look up the `topics.id` for a `<course>.unit-N.<name>` slug.

    Tries name-based heuristics on the current curriculum: the only
    structured key in the seed tree is `(course_slug, unit_n, topic_n)`,
    so we filter by `(course, unit)` and pick the topic whose name token
    overlaps the slug tail.
    """
    from app.core.supabase import get_supabase

    sb = get_supabase()
    if sb is None:
        return None

    course_slug, unit_n, topic_tail = parse_topic_slug(topic_slug)

    courses = sb.table("courses").select("id, slug").eq("slug", course_slug).execute()
    if not courses.data:
        return None
    course_id = courses.data[0]["id"]

    units = (
        sb.table("units")
        .select("id, n")
        .eq("course_id", course_id)
        .eq("n", unit_n)
        .execute()
    )
    if not units.data:
        return None
    unit_id = units.data[0]["id"]

    topics = (
        sb.table("topics")
        .select("id, name, n")
        .eq("unit_id", unit_id)
        .order("n")
        .execute()
    )
    if not topics.data:
        return None

    # Pick whichever topic's name contains the most slug-tail tokens.
    needle_tokens = {tok for tok in topic_tail.lower().split("-") if len(tok) > 2}
    best = topics.data[0]
    best_score = -1
    for row in topics.data:
        haystack = row["name"].lower()
        score = sum(1 for tok in needle_tokens if tok in haystack)
        if score > best_score:
            best_score = score
            best = row
    return best


_NOISE_TERMS = {
    "attribution information",
    "citation information",
    "section summary",
    "conceptual questions",
    "problems & exercises",
    "problems exercises",
    "footnotes",
    "creative commons",
    "openstax",
    "rice university",
    "this book",
    "section learning objectives",
    "learning objectives",
    "preview",
    "study tip",
    "homework problems",
    "review questions",
}


_UNICODE_FIXUPS = {
    "−": "-",  # U+2212 minus sign → ASCII hyphen
    "–": "-",  # U+2013 en dash → ASCII hyphen
    "—": "-",  # U+2014 em dash → ASCII hyphen
    "×": "*",  # multiplication sign → ASCII star
    "·": "*",  # middle dot → ASCII star
    " ": " ",  # NBSP → space
}


def _ascii_fix(text: str) -> str:
    """Normalise unicode glyphs to ASCII so model-emitted LaTeX matches the
    required-equation list. The validator strips spaces but is char-sensitive,
    so e.g. ``F = − kx`` (U+2212) must become ``F = -kx`` (ASCII -) to match
    the model's ``$F = -kx$`` output."""
    out = text
    for src, dst in _UNICODE_FIXUPS.items():
        out = out.replace(src, dst)
    return out


def _dedupe_doubled(token: str) -> str:
    """Collapse OpenStax MathML duplicates like ``FF`` / ``f=1T.f=1T.`` → ``F``.

    Live OpenStax pages serve MathML without TeX annotations, so the B1
    extractor's tag-strip leaves every glyph echoed (`<mi>F</mi><mi>F</mi>`
    → ``FF``). We pattern-match the "first half == second half" case and
    keep just the first half. Safe no-op on already-clean strings.
    """
    s = token.strip()
    if len(s) < 2:
        return s
    # Even-length whole-string duplicate (FF, xx, kk, etc.).
    if len(s) % 2 == 0:
        half = len(s) // 2
        if s[:half] == s[half:]:
            return s[:half].strip(".,;: ")
    # "expr.expr." style — same content repeated with a separator.
    for sep in (". ", " "):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 2 and parts[0].strip() == parts[1].strip(". "):
                return parts[0].strip(".,;: ")
    return s


def _clean_terms_and_equations(section: Section) -> Section:
    """Run the OpenStax-noise filters over a Section in place + return it.

    Drops dedup-doubled junk, allow-listed boilerplate ("Attribution
    information"), and overly-short fragments. This is a CLI-side helper —
    keeps the B1 extractor untouched while letting B2 generation see
    clean required-token lists.
    """
    cleaned_eqs: list[str] = []
    seen_eq: set[str] = set()
    for eq in section.equations:
        clean = _ascii_fix(_dedupe_doubled(eq))
        # Drop equations that are single-char / two-char garbage post-dedup.
        if len(clean) < 3 or "=" not in clean:
            continue
        # Drop overly-long arithmetic examples (`k = − 784 N − 1.20 × ...`)
        # and anything that has 3+ digits — the validator wants the
        # canonical symbolic form, not specific numeric instances.
        digit_count = sum(1 for ch in clean if ch.isdigit())
        if len(clean) > 30 or digit_count > 3:
            continue
        # Drop instances with raw scientific notation / measurement units.
        if any(unit in clean for unit in ("kg", "N/m", "rad/s", "Hz")):
            continue
        # Drop MathML-mangled equations. OpenStax MathML wraps each glyph
        # in its own <mi>, so when the source uses the "net" prefix the
        # extracted token list reads like `net W = ( net F ) Δ s` or
        # `net W=net τθ`. Substring check catches both spaced and glued
        # cases. Also drop forms with two consecutive single-digit tokens
        # (e.g. `KE rot = 1 2 Iω 2` ← `(1/2)Iω²` mangled).
        low = clean.lower()
        if low.count("net") >= 2 or " net" in low or "=net" in low:
            continue
        if re.search(r"\b\d\s+\d\b", clean):
            continue
        key = clean.lower().replace(" ", "")
        if key in seen_eq:
            continue
        seen_eq.add(key)
        cleaned_eqs.append(clean)
    section.equations = cleaned_eqs

    cleaned_terms: list[str] = []
    seen_term: set[str] = set()
    for term in section.named_terms:
        clean = _dedupe_doubled(term)
        low = clean.lower().strip()
        if not low or low in _NOISE_TERMS:
            continue
        if len(low) < 3 or len(low) > 50:
            continue
        # Reject pure-numeric or symbol-noise terms.
        if not any(ch.isalpha() for ch in low):
            continue
        if low in seen_term:
            continue
        seen_term.add(low)
        cleaned_terms.append(clean)
    section.named_terms = cleaned_terms
    return section


def _merge_sections(sections: list[Section], topic_slug: str) -> Section:
    """Combine multi-section topics (e.g. ch-16/16-1..16-3) into one Section
    so the chunker has the full sweep to pack."""
    if len(sections) == 1:
        return sections[0]
    merged = Section(slug=topic_slug, title=topic_slug)
    seen_eq: set[str] = set()
    seen_term: set[str] = set()
    for s in sections:
        merged.paragraphs.extend(s.paragraphs)
        for e in s.equations:
            if e.lower() not in seen_eq:
                seen_eq.add(e.lower())
                merged.equations.append(e)
        for t in s.named_terms:
            if t.lower() not in seen_term:
                seen_term.add(t.lower())
                merged.named_terms.append(t)
        # `source_url` keeps the first section's URL for provenance.
        if not merged.source_url:
            merged.source_url = s.source_url
    return merged


def _expand_course_filter(
    course: str | None, topic_slug: str | None
) -> list[str]:
    """Return the list of topic slugs to run for a `--course` / `--topic-slug` pair.

    Precedence (highest first):

      1. ``--topic-slug`` always wins (single-topic run).
      2. ``--course all`` → every key in mapping.yaml.
      3. ``--course <prefix>`` → mapping keys starting with ``<prefix>.``.
      4. Neither flag → empty list (caller errors out — argparse requires one).
    """
    from app.content.sources import load_mapping

    mapping = load_mapping()
    if topic_slug:
        return [topic_slug]
    if not course:
        return []
    if course.lower() == "all":
        return list(mapping.keys())
    prefix = course if course.endswith(".") else f"{course}."
    return [k for k in mapping.keys() if k.startswith(prefix)]


def _fixture_url_for(topic_slug: str) -> str | None:
    """If a local fixture covers this topic, return its file:// URL.

    Only oscillations is covered today (the B0 spike fixture). Future
    fixtures dropped into `app/content/fixtures/` will be auto-detected
    by filename convention (`<topic-key>.txt`) — left as a follow-up.
    """
    if topic_slug == "ap-physics-1.unit-7.oscillations":
        path = FIXTURE_DIR / "openstax-cp2e-ch16.txt"
        if path.exists():
            return path.as_uri()
    return None


async def _extract_for_topic(
    topic_slug: str, *, prefer_fixture: bool = False
) -> tuple[Section, list[SectionRef]]:
    """Extract + merge all sections configured for a topic in mapping.yaml."""
    refs = resolve_topic(topic_slug)
    sections: list[Section] = []

    fixture_url = _fixture_url_for(topic_slug) if prefer_fixture else None
    if fixture_url:
        sections.append(extract_section(fixture_url))
    else:
        for ref in refs:
            log.info("content_extract_section", topic=topic_slug, url=ref.url)
            sections.append(extract_section(ref.url))

    # OpenStax 2026 readers ship MathML *without* TeX annotations, so the B1
    # extractor's strip-tags fallback leaves doubled glyphs ("FF", "f=1T.f=1T.").
    # Clean here (CLI-side) rather than rewriting the extractor, per the
    # "extend, don't rewrite" guideline.
    sections = [_clean_terms_and_equations(s) for s in sections]
    merged = _merge_sections(sections, topic_slug)
    merged = _clean_terms_and_equations(merged)
    return merged, refs


def _serialise_vector(vec: list[float]) -> str:
    """Format a vector for pgvector — `[v1,v2,...]` works as a string literal."""
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand: ingest
# ─────────────────────────────────────────────────────────────────────────────
async def cmd_ingest(args: argparse.Namespace) -> int:
    topic_slug: str = args.topic_slug
    prefer_fixture: bool = args.fixture

    log.info("content_ingest_start", topic=topic_slug, fixture=prefer_fixture)
    merged, refs = await _extract_for_topic(
        topic_slug, prefer_fixture=prefer_fixture
    )
    chunks: list[Chunk] = chunk_section(merged)
    print(
        f"[ingest] {topic_slug}: {len(merged.paragraphs)} paragraphs "
        f"-> {len(chunks)} chunks",
        file=sys.stderr,
    )
    if not chunks:
        print("[ingest] no chunks produced — aborting", file=sys.stderr)
        return 2

    # Look up the real topic_id in Supabase. Without it, we have nothing to
    # write — fail loud rather than silently no-op.
    from app.core.supabase import get_supabase

    sb = get_supabase()
    if sb is None:
        print(
            "[ingest] Supabase is not configured — set SUPABASE_URL + "
            "SUPABASE_SERVICE_ROLE_KEY",
            file=sys.stderr,
        )
        return 3
    topic = _resolve_topic_in_supabase(topic_slug)
    if topic is None:
        print(
            f"[ingest] could not find a topic row for {topic_slug!r}",
            file=sys.stderr,
        )
        return 4
    topic_id: str = topic["id"]

    # Embed.
    embedder = args._embedder or get_embedder()
    vectors = await embedder.embed_chunks(chunks)
    if len(vectors) != len(chunks):
        print(
            f"[ingest] embedder returned {len(vectors)} vectors for "
            f"{len(chunks)} chunks — aborting",
            file=sys.stderr,
        )
        return 5

    # Idempotency: delete prior chunks for this topic, then insert fresh.
    sb.table("lesson_embeddings").delete().eq("topic_id", topic_id).execute()
    rows = [
        {
            "topic_id": topic_id,
            "ordinal": c.ordinal,
            "text": c.text,
            "source_url": c.source_url or (refs[0].url if refs else None),
            "embedding": _serialise_vector(v),
        }
        for c, v in zip(chunks, vectors, strict=True)
    ]
    # Supabase REST inserts cap somewhere around 1MB per request — our worst
    # case is ~30 chunks × ~1500 bytes ≈ well under, so one shot is fine.
    sb.table("lesson_embeddings").insert(rows).execute()

    # Mark provenance — B2's generator will overwrite this when it produces
    # the actual lesson content, but stamping it now means `verify` can see
    # which topics have been ingested.
    provenance = {
        "source": refs[0].book.attribution if refs else "unknown",
        "source_urls": [r.url for r in refs],
        "license": refs[0].book.license if refs else None,
        "model_embed": embedder._model if hasattr(embedder, "_model") else None,
        "chunk_count": len(chunks),
        "stage": "ingested",
    }
    sb.table("topics").update({"content_provenance": provenance}).eq(
        "id", topic_id
    ).execute()

    print(
        f"[ingest] wrote {len(rows)} chunks for {topic['name']!r} "
        f"(topic_id={topic_id})",
        file=sys.stderr,
    )
    print(f"chunks_written={len(rows)}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand: generate
# ─────────────────────────────────────────────────────────────────────────────
def _load_chunks_from_supabase(sb: Any, topic_id: str, limit: int = 12) -> list[Chunk]:
    """Read top-N chunks for a topic from `lesson_embeddings`, ordered by
    ordinal. The validator's source context comes from these rows."""
    q = (
        sb.table("lesson_embeddings")
        .select("ordinal, text, source_url")
        .eq("topic_id", topic_id)
        .order("ordinal")
        .limit(limit)
        .execute()
    )
    rows = q.data or []
    return [
        Chunk(
            ordinal=r["ordinal"],
            text=r["text"],
            source_url=r.get("source_url") or "",
        )
        for r in rows
    ]


def _format_retry_instructions(report: ValidationReport) -> str:
    """Build the `extra_instructions` block fed back into the generator."""
    lines: list[str] = ["The previous attempt failed these validator checks:"]
    for f in report.failures[:10]:
        lines.append(f"  • {f}")
    if report.missing_terms:
        lines.append(
            f"\nDROPPED REQUIRED TERMS — include each at least once: "
            f"{report.missing_terms}"
        )
    if report.missing_equations:
        lines.append(
            f"\nDROPPED REQUIRED EQUATIONS — include each literally inside "
            f"$...$ delimiters: {report.missing_equations}"
        )
    lines.append(
        "\nFix every issue above. Keep the 8-step structure intact and stay "
        "in Aria's voice. All math (single variables included) must stay "
        "inside $...$ or $$...$$ delimiters."
    )
    return "\n".join(lines)


async def cmd_generate(args: argparse.Namespace) -> int:
    topic_slug: str = args.topic_slug
    force: bool = args.force
    dry_run: bool = args.dry_run

    log.info("content_generate_cli_start", topic=topic_slug, force=force, dry_run=dry_run)

    # Resolve topic + required terms/equations from a fresh extract.
    refs = resolve_topic(topic_slug)
    merged, _ = await _extract_for_topic(topic_slug, prefer_fixture=args.fixture)
    required_terms = list(merged.named_terms)
    required_equations = list(merged.equations)

    # Cap the required-token list — extractors can surface dozens of bolded
    # phrases, most of which are noise. Top-N is plenty for coverage.
    required_terms = required_terms[:8]
    required_equations = required_equations[:5]

    from app.core.supabase import get_supabase

    sb = getattr(args, "_supabase", None) or get_supabase()
    if sb is None:
        print(
            "[generate] Supabase is not configured — set SUPABASE_URL + "
            "SUPABASE_SERVICE_ROLE_KEY",
            file=sys.stderr,
        )
        return 3

    topic = _resolve_topic_in_supabase(topic_slug)
    if topic is None:
        print(
            f"[generate] could not find a topic row for {topic_slug!r}",
            file=sys.stderr,
        )
        return 4
    topic_id: str = topic["id"]

    # Load source chunks from Supabase (requires a prior `ingest` run).
    source_chunks = _load_chunks_from_supabase(sb, topic_id, limit=12)
    if not source_chunks:
        print(
            f"[generate] no chunks found for topic {topic_id!r}; run "
            f"`ingest --topic-slug {topic_slug}` first",
            file=sys.stderr,
        )
        return 6

    print(
        f"[generate] {topic_slug}: terms={required_terms}",
        file=sys.stderr,
    )
    print(
        f"[generate]   equations={required_equations}",
        file=sys.stderr,
    )
    print(
        f"[generate]   source chunks loaded: {len(source_chunks)}",
        file=sys.stderr,
    )

    generator: LessonGenerator = (
        getattr(args, "_generator", None) or LessonGenerator()
    )

    parsed: LessonContent | None = None
    report: ValidationReport | None = None
    extra_instructions: str | None = None
    retries_used = 0

    for attempt in range(3):
        retries_used = attempt
        print(
            f"[generate] attempt {attempt + 1}/3 — calling "
            f"{generator._model} ...",
            file=sys.stderr,
        )
        parsed = await generator.generate(
            topic_name=topic["name"],
            required_terms=required_terms,
            required_equations=required_equations,
            source_chunks=source_chunks,
            extra_instructions=extra_instructions,
        )
        report = validate(parsed, required_terms, required_equations)
        print(
            f"[generate]   validator: ok={report.ok} "
            f"coverage={report.coverage_pct}% "
            f"failures={len(report.failures)}",
            file=sys.stderr,
        )
        for f in report.failures:
            print(f"      - {f}", file=sys.stderr)
        if report.ok:
            break
        extra_instructions = _format_retry_instructions(report)

    assert parsed is not None
    assert report is not None

    if not report.ok:
        # After 3 fails, route to the human-review queue.
        notes = "Auto-generation failed all 3 attempts.\n\n" + "\n".join(
            f"- {f}" for f in report.failures
        )
        try:
            sb.table("content_review").upsert(
                {"topic_id": topic_id, "status": "pending", "notes": notes}
            ).execute()
        except Exception as e:  # noqa: BLE001
            log.warning("content_review_upsert_failed", error=str(e))
        print(
            "[generate] FAILED — wrote content_review row "
            f"(topic_id={topic_id})",
            file=sys.stderr,
        )
        if dry_run:
            print(json.dumps(parsed.model_dump(), indent=2, ensure_ascii=False))
        return 7

    if dry_run:
        print(json.dumps(parsed.model_dump(), indent=2, ensure_ascii=False))
        print(
            f"[generate] DRY RUN — would persist topic_id={topic_id} "
            f"(retries={retries_used})",
            file=sys.stderr,
        )
        return 0

    # Build provenance + persist.
    source_url = refs[0].url if refs else merged.source_url
    attribution = refs[0].book.attribution if refs else None
    license_str = refs[0].book.license if refs else None
    embedder_model = settings.gemini_model_embed
    model_generate = generator._model

    provenance: dict[str, Any] = {
        "source": refs[0].book.slug if refs else "unknown",
        "source_url": source_url,
        "source_urls": [r.url for r in refs],
        "license": license_str,
        "attribution": attribution,
        "chunk_ids": [c.ordinal for c in source_chunks],
        "model_generate": model_generate,
        "model_embed": embedder_model,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "validator_version": VALIDATOR_VERSION,
        "human_reviewed": False,
        "hash": compute_provenance_hash(source_url, model_generate, VALIDATOR_VERSION),
        "stage": "generated",
    }

    persister = LessonPersister(sb)
    try:
        await persister.persist(
            topic_id=topic_id,
            content=parsed,
            provenance=provenance,
            human_reviewed=False,
            force=force,
        )
    except HumanReviewedConflict as e:
        print(f"[generate] {e}", file=sys.stderr)
        return 8

    print(
        f"[generate] OK — persisted lesson for {topic['name']!r} "
        f"(topic_id={topic_id}, retries={retries_used}, "
        f"coverage={report.coverage_pct}%)",
        file=sys.stderr,
    )
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand: quiz
# ─────────────────────────────────────────────────────────────────────────────
async def cmd_quiz(args: argparse.Namespace) -> int:
    """Generate + validate + persist a 3-question quiz set for one topic.

    Requires that the topic already has lesson content (`topics.content`)
    AND ingested chunks (`lesson_embeddings`). The generator anchors
    questions in the lesson the student saw — generating quizzes for an
    un-taught topic gives the model nothing concrete to probe.
    """
    from app.content.quiz_generator import QuizGenerator
    from app.content.quiz_persister import QuizPersister
    from app.content.quiz_validator import (
        VALIDATOR_VERSION as QUIZ_VALIDATOR_VERSION,
    )
    from app.content.quiz_validator import validate as validate_quiz
    from app.content.schema import LessonContent

    topic_slug: str = args.topic_slug
    dry_run: bool = args.dry_run
    log.info("content_quiz_cli_start", topic=topic_slug, dry_run=dry_run)

    from app.core.supabase import get_supabase

    sb = getattr(args, "_supabase", None) or get_supabase()
    if sb is None:
        print(
            "[quiz] Supabase is not configured — set SUPABASE_URL + "
            "SUPABASE_SERVICE_ROLE_KEY",
            file=sys.stderr,
        )
        return 3

    topic = _resolve_topic_in_supabase(topic_slug)
    if topic is None:
        print(
            f"[quiz] could not find a topic row for {topic_slug!r}",
            file=sys.stderr,
        )
        return 4
    topic_id: str = topic["id"]

    # Lesson content for prompt anchoring (optional but strongly preferred).
    full_topic_q = (
        sb.table("topics")
        .select("id, name, content")
        .eq("id", topic_id)
        .limit(1)
        .execute()
    )
    full_rows = full_topic_q.data or []
    if not full_rows:
        print(f"[quiz] topic {topic_id!r} not found", file=sys.stderr)
        return 4
    lesson_raw = full_rows[0].get("content")
    lesson: LessonContent | None = None
    if lesson_raw:
        try:
            lesson = LessonContent.model_validate({"items": lesson_raw})
        except Exception as e:  # noqa: BLE001
            log.warning("quiz_lesson_parse_failed", error=str(e))

    # Source chunks for fact-checking.
    source_chunks = _load_chunks_from_supabase(sb, topic_id, limit=8)
    if not source_chunks:
        print(
            f"[quiz] no chunks for topic {topic_id!r}; run `ingest` first",
            file=sys.stderr,
        )
        return 6

    print(
        f"[quiz] {topic_slug}: lesson={'yes' if lesson else 'no'} "
        f"chunks={len(source_chunks)}",
        file=sys.stderr,
    )

    generator = getattr(args, "_quiz_generator", None) or QuizGenerator()

    parsed = None
    report = None
    extra_instructions: str | None = None
    retries_used = 0
    for attempt in range(3):
        retries_used = attempt
        print(
            f"[quiz] attempt {attempt + 1}/3 — calling {generator._model} ...",
            file=sys.stderr,
        )
        parsed = await generator.generate(
            topic_name=topic["name"],
            lesson=lesson,
            source_chunks=source_chunks,
            extra_instructions=extra_instructions,
        )
        report = validate_quiz(parsed)
        print(
            f"[quiz]   validator: ok={report.ok} failures={len(report.failures)}",
            file=sys.stderr,
        )
        for f in report.failures:
            print(f"      - {f}", file=sys.stderr)
        if report.ok:
            break
        extra_instructions = (
            "The previous attempt failed these validator checks:\n"
            + "\n".join(f"  • {f}" for f in report.failures[:10])
            + "\nFix every issue above. Re-read each correct_idx against the "
            "lesson + source before emitting."
        )

    assert parsed is not None
    assert report is not None

    if not report.ok:
        print(
            "[quiz] FAILED — 3 attempts exhausted; not persisting",
            file=sys.stderr,
        )
        if dry_run:
            print(parsed.model_dump_json(indent=2))
        return 7

    if dry_run:
        print(parsed.model_dump_json(indent=2))
        print(
            f"[quiz] DRY RUN — would persist topic_id={topic_id} "
            f"(retries={retries_used})",
            file=sys.stderr,
        )
        return 0

    import datetime as _dt2

    provenance: dict[str, Any] = {
        "model_generate": generator._model,
        "validator_version": QUIZ_VALIDATOR_VERSION,
        "generated_at": _dt2.datetime.now(_dt2.timezone.utc).isoformat(),
        "lesson_anchored": lesson is not None,
        "chunk_ids": [c.ordinal for c in source_chunks],
        "stage": "generated",
    }

    persister = QuizPersister(sb)
    n = await persister.persist(
        topic_id=topic_id,
        quiz=parsed,
        provenance=provenance,
    )
    print(
        f"[quiz] OK — wrote {n} questions for {topic['name']!r} "
        f"(topic_id={topic_id}, retries={retries_used})",
        file=sys.stderr,
    )
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand: verify
# ─────────────────────────────────────────────────────────────────────────────
async def cmd_verify(args: argparse.Namespace) -> int:
    from app.core.supabase import get_supabase

    sb = get_supabase()
    if sb is None:
        print("[verify] Supabase is not configured", file=sys.stderr)
        return 3

    topics = sb.table("topics").select("id, name, content_provenance").execute()
    rows = topics.data or []

    failures: list[str] = []
    passed = 0
    for row in rows:
        tid = row["id"]
        prov = row.get("content_provenance")
        chunks_q = (
            sb.table("lesson_embeddings")
            .select("ordinal", count="exact")
            .eq("topic_id", tid)
            .execute()
        )
        n_chunks = chunks_q.count or len(chunks_q.data or [])
        if not prov:
            failures.append(f"{row['name']!r}: no content_provenance")
            continue
        if n_chunks < 3:
            failures.append(f"{row['name']!r}: only {n_chunks} chunks")
            continue
        passed += 1

    print(
        f"[verify] {passed} OK / {len(failures)} FAIL out of {len(rows)} topics",
        file=sys.stderr,
    )
    for f in failures:
        print(f"  - {f}", file=sys.stderr)
    return 0 if not failures else 1


# ─────────────────────────────────────────────────────────────────────────────
# argparse
# ─────────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.content.cli",
        description="Content pipeline CLI (B1: ingest + verify).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest one or more topics into lesson_embeddings.")
    g_ing = p_ingest.add_mutually_exclusive_group(required=True)
    g_ing.add_argument(
        "--topic-slug",
        help="Single-topic run, e.g. ap-physics-1.unit-7.oscillations",
    )
    g_ing.add_argument(
        "--course",
        help=(
            "Bulk run: 'all' for every topic in mapping.yaml, or a course "
            "prefix like 'ap-physics-1'."
        ),
    )
    p_ingest.add_argument(
        "--fixture",
        action="store_true",
        help="Use the local fixture if one exists (offline testing).",
    )

    p_generate = sub.add_parser(
        "generate",
        help="Generate + validate + persist an 8-step lesson for one or more topics.",
    )
    g_gen = p_generate.add_mutually_exclusive_group(required=True)
    g_gen.add_argument(
        "--topic-slug",
        help="Single-topic run, e.g. ap-physics-1.unit-7.oscillations",
    )
    g_gen.add_argument(
        "--course",
        help=(
            "Bulk run: 'all' or a course prefix. Topics without ingested "
            "chunks are skipped with a logged warning."
        ),
    )
    p_generate.add_argument(
        "--force",
        action="store_true",
        help="Overwrite human-reviewed lessons with matching provenance hash.",
    )
    p_generate.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated lesson JSON to stdout instead of writing.",
    )
    p_generate.add_argument(
        "--fixture",
        action="store_true",
        help="Use the local OpenStax fixture for the term/equation extract "
        "instead of the live HTTPS fetch.",
    )

    p_quiz = sub.add_parser(
        "quiz",
        help="Generate + validate + persist 3 quiz questions for one or more topics.",
    )
    g_quiz = p_quiz.add_mutually_exclusive_group(required=True)
    g_quiz.add_argument(
        "--topic-slug",
        help="Single-topic run, e.g. ap-physics-1.unit-7.oscillations",
    )
    g_quiz.add_argument(
        "--course",
        help="Bulk run: 'all' or a course prefix.",
    )
    p_quiz.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated QuizSet JSON to stdout instead of writing.",
    )

    p_verify = sub.add_parser("verify", help="Verify ingest state.")
    g = p_verify.add_mutually_exclusive_group()
    g.add_argument("--topic-slug")
    g.add_argument("--course")
    g.add_argument("--all", action="store_true")

    return p


async def _bulk_run(
    cmd: Any,
    args: argparse.Namespace,
    slugs: list[str],
    *,
    label: str,
) -> int:
    """Iterate ``slugs``, invoking ``cmd(args)`` for each. Returns the worst rc.

    Each topic gets its own ``args`` clone so failures don't infect the rest
    of the batch. We tally per-topic exit codes and print a concise summary
    at the end — handy when the run is long.
    """
    from copy import copy as _copy

    rcs: list[tuple[str, int]] = []
    for slug in slugs:
        per_args = _copy(args)
        per_args.topic_slug = slug
        per_args.course = None  # prevent re-entry
        print(f"[{label}] === topic {slug} ===", file=sys.stderr)
        try:
            rc = await cmd(per_args)
        except Exception as e:  # noqa: BLE001
            log.warning(f"content_{label}_topic_error", topic=slug, error=str(e))
            print(f"[{label}] ERROR for {slug}: {e}", file=sys.stderr)
            rc = 99
        rcs.append((slug, rc))
    n_ok = sum(1 for _, rc in rcs if rc == 0)
    print(
        f"[{label}] DONE — {n_ok}/{len(rcs)} topics succeeded",
        file=sys.stderr,
    )
    for slug, rc in rcs:
        if rc != 0:
            print(f"[{label}]   FAIL rc={rc}: {slug}", file=sys.stderr)
    return 0 if n_ok == len(rcs) else 1


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    _load_env()
    args = build_parser().parse_args(argv)
    # Allow tests to inject an embedder via setattr; default to None and the
    # ingest cmd will fall back to get_embedder().
    args._embedder = getattr(args, "_embedder", None)

    if args.command in ("ingest", "generate", "quiz"):
        # Bulk vs single-topic dispatch.
        slugs = _expand_course_filter(
            getattr(args, "course", None),
            getattr(args, "topic_slug", None),
        )
        if not slugs:
            print(
                f"[{args.command}] no topics matched — supply --topic-slug "
                "or --course <prefix|all>",
                file=sys.stderr,
            )
            return 1
        cmd: Any
        if args.command == "ingest":
            cmd = cmd_ingest
        elif args.command == "generate":
            cmd = cmd_generate
        else:
            cmd = cmd_quiz
        if len(slugs) == 1:
            args.topic_slug = slugs[0]
            return asyncio.run(cmd(args))
        return asyncio.run(_bulk_run(cmd, args, slugs, label=args.command))
    if args.command == "verify":
        return asyncio.run(cmd_verify(args))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
