"""Tests for the B2 content pipeline (generator + validator + persister + CLI).

All tests run offline:
  • The Gemini SDK is stubbed inside ``LessonGenerator.gemini.client``.
  • Supabase calls are mocked with ``MagicMock``.

Real cloud verification is documented in docs/content-pipeline.md and was
run once by hand on the Oscillations topic.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("DEV_MODE", "true")

from app.content import cli, generator, persister, validator  # noqa: E402
from app.content.chunker import Chunk  # noqa: E402
from app.content.schema import LessonContent, LessonStep  # noqa: E402
from app.core.config import settings  # noqa: E402


# ─── helpers ─────────────────────────────────────────────────────────────────
def _valid_lesson() -> LessonContent:
    """Hand-built lesson that satisfies all three validator gates.

    Mirrors the seed-data Oscillations lesson but with $...$ math formatting
    and the required restoring-force term added (per the worked example).
    """
    return LessonContent(
        items=[
            LessonStep(
                tts="Preparing your lesson.",
                html="Preparing your lesson…",
                dur="00:00",
            ),
            LessonStep(
                tts="Pluck a guitar string and watch it wobble around its rest line.",
                html='Pluck a guitar string and watch it wobble around its <span class="hl-y">rest line</span>.',
                dur="01:20",
            ),
            LessonStep(
                tts="That rest spot is called equilibrium — the calm centre of every oscillation.",
                html='That rest spot is called <span class="hl-b">equilibrium</span> — the calm centre.',
                dur="02:30",
            ),
            LessonStep(
                tts="The pull that yanks the string back is the restoring force.",
                html='The pull that yanks the string back is the <span class="hl-p">restoring force</span>.',
                dur="04:00",
            ),
            LessonStep(
                tts="How far you pulled it is the amplitude — the oscillation's energy.",
                html='How far you pulled it is the <span class="hl-g">amplitude</span>, the oscillation\'s energy.',
                dur="05:30",
            ),
            LessonStep(
                tts="One full back-and-forth cycle takes one period — we call it T.",
                html='One full back-and-forth is the <span class="hl-y">period</span> $T$.',
                dur="07:30",
            ),
            LessonStep(
                tts="How often it repeats is the frequency. Inverse of the period.",
                html='How often it repeats is the <span class="hl-b">frequency</span>, because $T = 1/f$ always holds.',
                dur="09:50",
            ),
            LessonStep(
                tts="Put it together: T equals one over f. That's the whole game.",
                html='Put it together: <span class="hl-g">$T = 1/f$</span>. So period is one over frequency.',
                dur="12:40",
            ),
        ]
    )


REQUIRED_TERMS = ["amplitude", "period", "frequency", "equilibrium", "restoring force"]
REQUIRED_EQUATIONS = ["T = 1/f"]


# ─── validator — positive case ───────────────────────────────────────────────
def test_validator_passes_on_well_formed_lesson() -> None:
    report = validator.validate(_valid_lesson(), REQUIRED_TERMS, REQUIRED_EQUATIONS)
    assert report.ok, f"expected pass, failures: {report.failures}"
    assert report.coverage_pct == 100
    assert report.missing_terms == []
    assert report.missing_equations == []


# ─── validator — negative cases ──────────────────────────────────────────────
def test_validator_flags_missing_term() -> None:
    lesson = _valid_lesson()
    # Strip "restoring force" out of step 3.
    lesson.items[3].html = "The pull yanks the string back, hard."
    lesson.items[3].tts = "The pull yanks the string back, hard."
    report = validator.validate(lesson, REQUIRED_TERMS, REQUIRED_EQUATIONS)
    # Coverage = 5/6 = 83% → below 90% threshold.
    assert not report.ok
    assert "restoring force" in [t.lower() for t in report.missing_terms]


def test_validator_flags_bare_ascii_math() -> None:
    lesson = _valid_lesson()
    # Replace last step's $T = 1/f$ with a bare ASCII equation.
    lesson.items[7].html = 'Put it together: <span class="hl-g">T = 1/f</span>. So period equals one over frequency.'
    report = validator.validate(lesson, REQUIRED_TERMS, REQUIRED_EQUATIONS)
    assert not report.ok
    assert any("bare ASCII math" in f for f in report.failures)


def test_validator_flags_too_long_tts() -> None:
    # Pydantic enforces max_length=120 at schema time — verify the schema
    # rejects an over-length tts before the validator ever sees it.
    with pytest.raises(Exception):  # pydantic.ValidationError
        LessonStep(
            tts="x" * 121,
            html='<span class="hl-y">x</span>',
            dur="00:30",
        )

    # And the validator catches a sneak-around: tts crafted to be exactly
    # 120 chars passes pydantic but the rest of the gates still flag a
    # missing equation / etc. We sidestep pydantic via model_construct.
    lesson = _valid_lesson()
    bad = LessonStep.model_construct(
        tts="x" * 130,
        html='<span class="hl-y">x</span>',
        dur="00:30",
    )
    lesson.items[1] = bad
    report = validator.validate(lesson, REQUIRED_TERMS, REQUIRED_EQUATIONS)
    assert not report.ok
    assert any("tts" in f and "120" in f for f in report.failures)


def test_validator_flags_non_monotonic_dur() -> None:
    lesson = _valid_lesson()
    lesson.items[5].dur = "00:30"  # earlier than step 4 (05:30)
    report = validator.validate(lesson, REQUIRED_TERMS, REQUIRED_EQUATIONS)
    assert not report.ok
    assert any("not monotonic" in f for f in report.failures)


def test_validator_flags_wrong_step_count() -> None:
    # Pydantic itself will reject a 7-item list — make sure we surface the
    # ValidationError shape cleanly.
    with pytest.raises(Exception):  # pydantic.ValidationError
        LessonContent(items=_valid_lesson().items[:7])


def test_validator_flags_zero_highlights_in_body_step() -> None:
    lesson = _valid_lesson()
    lesson.items[1].html = "no highlight here"
    report = validator.validate(lesson, REQUIRED_TERMS, REQUIRED_EQUATIONS)
    assert not report.ok
    assert any("expected exactly 1 highlight" in f for f in report.failures)


def test_validator_flags_disallowed_tag() -> None:
    lesson = _valid_lesson()
    lesson.items[1].html = '<p>nope <span class="hl-y">rest line</span></p>'
    report = validator.validate(lesson, REQUIRED_TERMS, REQUIRED_EQUATIONS)
    assert not report.ok
    assert any("disallowed html tags" in f for f in report.failures)


# ─── generator — stubbed Gemini call ─────────────────────────────────────────
async def test_generator_returns_parsed_lesson(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _valid_lesson()

    class _FakeResp:
        parsed = expected
        text = ""
        usage_metadata = MagicMock(
            prompt_token_count=400,
            candidates_token_count=900,
            total_token_count=1300,
        )

    class _FakeModels:
        async def generate_content(self, **kwargs: Any) -> Any:
            # Sanity-check the call shape — the generator passes the
            # configured PRO model, whatever it is pinned to.
            assert kwargs["model"] == settings.gemini_model_pro
            cfg = kwargs["config"]
            assert cfg["response_schema"] is LessonContent
            assert cfg["response_mime_type"] == "application/json"
            assert "system_instruction" in cfg
            assert "TOPIC" in kwargs["contents"]
            return _FakeResp()

    class _FakeAio:
        models = _FakeModels()

    class _FakeClient:
        aio = _FakeAio()

    gen = generator.LessonGenerator()
    # Bypass GeminiService construction by patching the .gemini property to
    # return an object whose `.client` is our fake.
    fake_service = MagicMock()
    fake_service.client = _FakeClient()
    monkeypatch.setattr(gen, "_gemini", fake_service)

    chunks = [Chunk(ordinal=0, text="Oscillation source text.", source_url="file://x")]
    out = await gen.generate(
        topic_name="Oscillations",
        required_terms=REQUIRED_TERMS,
        required_equations=REQUIRED_EQUATIONS,
        source_chunks=chunks,
    )
    assert isinstance(out, LessonContent)
    assert len(out.items) == 8
    assert out.items[0].tts == "Preparing your lesson."


async def test_generator_falls_back_to_text_when_parsed_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _valid_lesson()
    raw_json = expected.model_dump_json()

    class _FakeResp:
        parsed = None
        text = raw_json
        usage_metadata = None

    class _FakeModels:
        async def generate_content(self, **kwargs: Any) -> Any:
            return _FakeResp()

    class _FakeAio:
        models = _FakeModels()

    class _FakeClient:
        aio = _FakeAio()

    gen = generator.LessonGenerator()
    fake_service = MagicMock()
    fake_service.client = _FakeClient()
    monkeypatch.setattr(gen, "_gemini", fake_service)

    out = await gen.generate(
        topic_name="Oscillations",
        required_terms=REQUIRED_TERMS,
        required_equations=REQUIRED_EQUATIONS,
        source_chunks=[],
    )
    assert isinstance(out, LessonContent)


# ─── persister — archive + update + hash idempotency ─────────────────────────
async def test_persister_archives_and_updates() -> None:
    inserts: list[tuple[str, dict[str, Any]]] = []
    updates: list[dict[str, Any]] = []

    def _table(name: str) -> Any:
        q = MagicMock()
        if name == "topics":

            def _select(*a: Any, **kw: Any) -> Any:
                sel = MagicMock()
                sel.eq.return_value = sel
                sel.limit.return_value = sel
                sel.execute.return_value = MagicMock(
                    data=[
                        {
                            "id": "t1",
                            "content": [{"prior": True}],
                            "content_provenance": {"hash": "old", "human_reviewed": False},
                        }
                    ]
                )
                return sel

            q.select.side_effect = _select

            def _update(payload: dict[str, Any]) -> Any:
                updates.append(payload)
                u = MagicMock()
                u.eq.return_value = u
                u.execute.return_value = MagicMock(data=[])
                return u

            q.update.side_effect = _update
            return q
        if name == "content_history":

            def _insert(payload: dict[str, Any]) -> Any:
                inserts.append((name, payload))
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=[])
                return ins

            q.insert.side_effect = _insert
            return q
        raise AssertionError(f"unexpected table {name!r}")

    sb = MagicMock()
    sb.table.side_effect = _table

    p = persister.LessonPersister(sb)
    out = await p.persist(
        topic_id="t1",
        content=_valid_lesson(),
        provenance={
            "source_url": "https://x",
            "model_generate": "gemini-pro-latest",
        },
    )
    assert len(inserts) == 1
    assert inserts[0][0] == "content_history"
    assert inserts[0][1]["topic_id"] == "t1"
    assert len(updates) == 1
    assert "content" in updates[0]
    assert "content_provenance" in updates[0]
    assert out["hash"]  # stamped


async def test_persister_refuses_overwrite_on_human_reviewed_match() -> None:
    fixed_hash = persister.compute_provenance_hash(
        "https://x", "gemini-pro-latest", validator.VALIDATOR_VERSION
    )

    def _table(name: str) -> Any:
        q = MagicMock()
        if name == "topics":
            sel = MagicMock()
            sel.eq.return_value = sel
            sel.limit.return_value = sel
            sel.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "t1",
                        "content": [{"x": 1}],
                        "content_provenance": {
                            "hash": fixed_hash,
                            "human_reviewed": True,
                        },
                    }
                ]
            )
            q.select.return_value = sel
            return q
        raise AssertionError(f"unexpected table {name!r}")

    sb = MagicMock()
    sb.table.side_effect = _table

    p = persister.LessonPersister(sb)
    with pytest.raises(persister.HumanReviewedConflict):
        await p.persist(
            topic_id="t1",
            content=_valid_lesson(),
            provenance={
                "source_url": "https://x",
                "model_generate": "gemini-pro-latest",
            },
        )


async def test_persister_force_overrides_human_reviewed() -> None:
    fixed_hash = persister.compute_provenance_hash(
        "https://x", "gemini-pro-latest", validator.VALIDATOR_VERSION
    )

    updates: list[dict[str, Any]] = []
    inserts: list[tuple[str, dict[str, Any]]] = []

    def _table(name: str) -> Any:
        q = MagicMock()
        if name == "topics":
            sel = MagicMock()
            sel.eq.return_value = sel
            sel.limit.return_value = sel
            sel.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "t1",
                        "content": [{"x": 1}],
                        "content_provenance": {
                            "hash": fixed_hash,
                            "human_reviewed": True,
                        },
                    }
                ]
            )
            q.select.return_value = sel

            def _update(payload: dict[str, Any]) -> Any:
                updates.append(payload)
                u = MagicMock()
                u.eq.return_value = u
                u.execute.return_value = MagicMock(data=[])
                return u

            q.update.side_effect = _update
            return q
        if name == "content_history":

            def _insert(payload: dict[str, Any]) -> Any:
                inserts.append((name, payload))
                ins = MagicMock()
                ins.execute.return_value = MagicMock(data=[])
                return ins

            q.insert.side_effect = _insert
            return q
        raise AssertionError(f"unexpected table {name!r}")

    sb = MagicMock()
    sb.table.side_effect = _table

    p = persister.LessonPersister(sb)
    await p.persist(
        topic_id="t1",
        content=_valid_lesson(),
        provenance={
            "source_url": "https://x",
            "model_generate": "gemini-pro-latest",
        },
        force=True,
    )
    assert len(updates) == 1
    assert len(inserts) == 1  # prior content archived


# ─── CLI generate — end-to-end with mocked generator + supabase ──────────────
async def test_cli_generate_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _valid_lesson()

    class _FakeGenerator:
        _model = "gemini-pro-latest"

        async def generate(self, **kwargs: Any) -> LessonContent:
            assert kwargs["topic_name"]
            return expected

    inserts: list[tuple[str, Any]] = []
    updates: list[dict[str, Any]] = []

    def _build_q() -> Any:
        q = MagicMock()
        q.select.return_value = q
        q.eq.return_value = q
        q.order.return_value = q
        q.limit.return_value = q
        return q

    def _table(name: str) -> Any:
        if name == "courses":
            q = _build_q()
            q.execute.return_value = MagicMock(
                data=[{"id": "c1", "slug": "ap-physics-1"}]
            )
            return q
        if name == "units":
            q = _build_q()
            q.execute.return_value = MagicMock(data=[{"id": "u1", "n": 7}])
            return q
        if name == "topics":
            q = _build_q()
            # First call: lookup → list of topics
            # Second call: select content + provenance for persist
            # Both routes through .select().eq().limit().execute()
            q.execute.side_effect = [
                # _resolve_topic_in_supabase: list of topics
                MagicMock(
                    data=[
                        {
                            "id": "t1",
                            "name": "Oscillations: Amplitude, Period & Frequency",
                            "n": 1,
                        }
                    ]
                ),
                # persister.persist: select current row
                MagicMock(
                    data=[
                        {
                            "id": "t1",
                            "content": None,
                            "content_provenance": None,
                        }
                    ]
                ),
            ]

            def _update(payload: dict[str, Any]) -> Any:
                updates.append(payload)
                u = _build_q()
                u.execute.return_value = MagicMock(data=[])
                return u

            q.update.side_effect = _update
            return q
        if name == "lesson_embeddings":
            q = _build_q()
            q.execute.return_value = MagicMock(
                data=[
                    {"ordinal": 0, "text": "chunk zero text", "source_url": "https://x"},
                    {"ordinal": 1, "text": "chunk one text",  "source_url": "https://x"},
                    {"ordinal": 2, "text": "chunk two text",  "source_url": "https://x"},
                ]
            )
            return q
        if name == "content_history":

            def _insert(payload: dict[str, Any]) -> Any:
                inserts.append((name, payload))
                ins = _build_q()
                ins.execute.return_value = MagicMock(data=[])
                return ins

            q = _build_q()
            q.insert.side_effect = _insert
            return q
        raise AssertionError(f"unexpected table {name!r}")

    sb = MagicMock()
    sb.table.side_effect = _table

    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: sb)
    import app.content.cli as cli_mod
    from app.content.extractors import Section

    # Pin the extractor output to a curated term/equation list so the
    # mocked generator's lesson satisfies the validator.
    async def _fake_extract(slug: str, *, prefer_fixture: bool = False) -> Any:
        sec = Section(
            slug="oscillations",
            title="Oscillations",
            source_url="https://openstax.org/books/college-physics-2e/pages/16-1",
        )
        sec.paragraphs = ["pretend prose"]
        sec.named_terms = REQUIRED_TERMS
        sec.equations = REQUIRED_EQUATIONS
        from app.content.sources import resolve_topic

        return sec, resolve_topic(slug)

    monkeypatch.setattr(cli_mod, "_extract_for_topic", _fake_extract)
    monkeypatch.setattr(cli_mod, "LessonGenerator", lambda: _FakeGenerator())

    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "generate",
            "--topic-slug",
            "ap-physics-1.unit-7.oscillations",
            "--fixture",
        ]
    )
    args._supabase = sb
    args._generator = _FakeGenerator()

    rc = await cli.cmd_generate(args)
    assert rc == 0, "expected happy path to return 0"
    assert len(updates) == 1
    update = updates[0]
    assert "content" in update
    assert "content_provenance" in update
    prov = update["content_provenance"]
    assert prov["model_generate"] == "gemini-pro-latest"
    assert prov["validator_version"] == validator.VALIDATOR_VERSION
    assert "hash" in prov
    assert prov["human_reviewed"] is False


async def test_cli_generate_dry_run_does_not_persist(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = _valid_lesson()

    class _FakeGenerator:
        _model = "gemini-pro-latest"

        async def generate(self, **kwargs: Any) -> LessonContent:
            return expected

    updates: list[dict[str, Any]] = []

    def _build_q() -> Any:
        q = MagicMock()
        q.select.return_value = q
        q.eq.return_value = q
        q.order.return_value = q
        q.limit.return_value = q
        return q

    def _table(name: str) -> Any:
        if name == "courses":
            q = _build_q()
            q.execute.return_value = MagicMock(
                data=[{"id": "c1", "slug": "ap-physics-1"}]
            )
            return q
        if name == "units":
            q = _build_q()
            q.execute.return_value = MagicMock(data=[{"id": "u1", "n": 7}])
            return q
        if name == "topics":
            q = _build_q()
            q.execute.return_value = MagicMock(
                data=[
                    {"id": "t1", "name": "Oscillations", "n": 1},
                ]
            )

            def _update(payload: dict[str, Any]) -> Any:
                updates.append(payload)
                u = _build_q()
                u.execute.return_value = MagicMock(data=[])
                return u

            q.update.side_effect = _update
            return q
        if name == "lesson_embeddings":
            q = _build_q()
            q.execute.return_value = MagicMock(
                data=[{"ordinal": 0, "text": "x", "source_url": "https://x"}]
            )
            return q
        raise AssertionError(f"unexpected table {name!r}")

    sb = MagicMock()
    sb.table.side_effect = _table

    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: sb)
    import app.content.cli as cli_mod
    from app.content.extractors import Section

    async def _fake_extract(slug: str, *, prefer_fixture: bool = False) -> Any:
        sec = Section(
            slug="oscillations", title="Oscillations",
            source_url="https://x",
        )
        sec.paragraphs = ["x"]
        sec.named_terms = REQUIRED_TERMS
        sec.equations = REQUIRED_EQUATIONS
        from app.content.sources import resolve_topic
        return sec, resolve_topic(slug)

    monkeypatch.setattr(cli_mod, "_extract_for_topic", _fake_extract)

    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "generate",
            "--topic-slug",
            "ap-physics-1.unit-7.oscillations",
            "--fixture",
            "--dry-run",
        ]
    )
    args._supabase = sb
    args._generator = _FakeGenerator()
    rc = await cli.cmd_generate(args)
    assert rc == 0
    assert updates == [], "dry-run must not write"
    out = capsys.readouterr().out
    # Generated JSON lands on stdout.
    assert '"tts"' in out
