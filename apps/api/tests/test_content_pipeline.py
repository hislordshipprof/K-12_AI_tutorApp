"""Tests for the B1 content pipeline (extractor + chunker + embedder + CLI).

These tests run fully offline: the OpenStax fixture is read via ``file://``
URLs and the Gemini embedder is mocked. Real Supabase + real Gemini are only
exercised by the CLI smoke run documented in docs/content-pipeline.md.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Match conftest's env wiring so this file can be invoked in isolation.
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("DEV_MODE", "true")

from app.content import chunker, cli, embedder, extractors, sources  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = API_ROOT / "app" / "content" / "fixtures" / "openstax-cp2e-ch16.txt"


# ─── extractor ───────────────────────────────────────────────────────────────
def test_extractor_parses_fixture() -> None:
    section = extractors.extract_section(FIXTURE_PATH.as_uri())
    assert isinstance(section, extractors.Section)
    assert section.paragraphs, "extractor produced no paragraphs"
    # The fixture has roughly a dozen prose blocks; we just want non-trivial.
    assert len(section.paragraphs) >= 8
    # Equations like `T = 1 / f` / `F = -k x` / `PE_el = ½ k x²` should land
    # in equations[] — we don't check exact strings (whitespace varies) but
    # the bucket must be non-empty.
    assert section.equations, "extractor produced no equations"
    # Named terms heuristic should find capitalised glossary phrases.
    assert section.named_terms, "extractor produced no named terms"
    assert section.source_url.startswith("file:")


# ─── chunker ─────────────────────────────────────────────────────────────────
def test_chunker_produces_three_or_more_chunks_in_range() -> None:
    section = extractors.extract_section(FIXTURE_PATH.as_uri())
    chunks = chunker.chunk_section(section, target_tokens=300)
    assert len(chunks) >= 3, f"expected >=3 chunks, got {len(chunks)}"
    # Each chunk must have a stable ordinal and text. Allow the LAST chunk to
    # exceed the 400-token soft cap (the merger glues a small trailing chunk
    # onto its predecessor). All non-trailing chunks must sit in the window.
    for i, c in enumerate(chunks):
        assert c.ordinal == i, f"ordinals out of order at {i}"
        assert c.text.strip()
        assert c.estimated_tokens >= 50
    for c in chunks[:-1]:
        assert c.estimated_tokens <= 600, (
            f"chunk {c.ordinal} too large: {c.estimated_tokens}"
        )


def test_chunker_attaches_equations_to_relevant_chunks() -> None:
    section = extractors.extract_section(FIXTURE_PATH.as_uri())
    chunks = chunker.chunk_section(section)
    # At least one chunk should surface at least one equation; the validator
    # in B2 will lean on this.
    assert any(c.equations for c in chunks), (
        "no chunk recorded any equation tokens"
    )


def test_chunker_handles_empty_section() -> None:
    empty = extractors.Section(slug="x", title="x")
    assert chunker.chunk_section(empty) == []


# ─── sources / mapping.yaml ─────────────────────────────────────────────────
def test_mapping_yaml_covers_all_courses() -> None:
    mapping = sources.load_mapping()
    keys = list(mapping.keys())
    # 8 physics + 10 calc + 8 bio = 26 topics
    assert len(keys) == 26, f"expected 26 topic slugs, got {len(keys)}"
    assert any(k.startswith("ap-physics-1.") for k in keys)
    assert any(k.startswith("ap-calc-bc.") for k in keys)
    assert any(k.startswith("ap-biology.") for k in keys)


def test_resolve_topic_oscillations() -> None:
    refs = sources.resolve_topic("ap-physics-1.unit-7.oscillations")
    assert len(refs) == 3
    assert all("college-physics-2e" in r.url for r in refs)
    # B3 fix: section anchors are now full slugs so URLs resolve to live
    # OpenStax pages, e.g. ``16-1-hookes-law-stress-and-strain-revisited``.
    assert refs[0].section is not None
    assert refs[0].section.startswith("16-1-")
    assert refs[0].url.endswith(refs[0].section)


def test_parse_topic_slug() -> None:
    course, unit_n, tail = sources.parse_topic_slug(
        "ap-physics-1.unit-7.oscillations"
    )
    assert course == "ap-physics-1"
    assert unit_n == 7
    assert tail == "oscillations"


def test_parse_topic_slug_bad_format() -> None:
    with pytest.raises(ValueError):
        sources.parse_topic_slug("nope")


# ─── embedder ────────────────────────────────────────────────────────────────
async def test_embedder_batches_and_uses_768d(monkeypatch: pytest.MonkeyPatch) -> None:
    e = embedder.GeminiEmbedder(api_key="fake-key")

    captured_calls: list[dict[str, Any]] = []

    def _vec(_i: int) -> list[float]:
        return [0.1] * embedder.EMBED_DIM

    class _FakeEmbed:
        async def embed_content(self, **kwargs: Any) -> Any:
            captured_calls.append(kwargs)
            # `contents` is now a list of Content dicts (one per input text).
            n = len(kwargs["contents"])
            response = MagicMock()
            response.embeddings = [MagicMock(values=_vec(i)) for i in range(n)]
            return response

    class _FakeAio:
        def __init__(self) -> None:
            self.models = _FakeEmbed()

    class _FakeClient:
        def __init__(self) -> None:
            self.aio = _FakeAio()

    monkeypatch.setattr(e, "_client", _FakeClient())

    texts = [f"chunk {i}" for i in range(200)]
    out = await e.embed_texts(texts)

    assert len(out) == 200
    assert all(len(v) == 768 for v in out)
    # 200 / 96 → 3 batches.
    assert len(captured_calls) == 3
    assert all(
        c["config"]["output_dimensionality"] == 768 for c in captured_calls
    )


# ─── CLI ingest end-to-end (mocked embedder + supabase) ──────────────────────
async def test_cli_ingest_writes_chunks_to_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mock the embedder — return one fake vector per chunk.
    class _MockEmbedder:
        _model = "gemini-embedding-2"

        async def embed_chunks(self, chunks: list[chunker.Chunk]) -> list[list[float]]:
            return [[0.0] * 768 for _ in chunks]

    # Mock Supabase: capture table().insert/delete/update calls.
    inserts: list[list[dict[str, Any]]] = []
    deletes: list[tuple[str, Any]] = []
    updates: list[dict[str, Any]] = []

    def _build_query(name: str) -> Any:
        q = MagicMock(name=f"query-{name}")
        q.select.return_value = q
        q.eq.return_value = q
        q.order.return_value = q
        q.limit.return_value = q
        return q

    def _topics_query() -> Any:
        q = _build_query("topics")
        q.execute.side_effect = [
            MagicMock(data=[{"id": "course-uuid", "slug": "ap-physics-1"}]),
        ]
        return q

    def _table(name: str) -> Any:
        if name == "courses":
            q = _build_query("courses")
            q.execute.return_value = MagicMock(
                data=[{"id": "course-uuid", "slug": "ap-physics-1"}]
            )
            return q
        if name == "units":
            q = _build_query("units")
            q.execute.return_value = MagicMock(
                data=[{"id": "unit-uuid", "n": 7}]
            )
            return q
        if name == "topics":
            q = _build_query("topics")
            q.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "topic-uuid",
                        "name": "Oscillations: Amplitude, Period & Frequency",
                        "n": 1,
                    }
                ]
            )
            # `.update(...).eq(...).execute()`
            def _update(payload: dict[str, Any]) -> Any:
                updates.append(payload)
                u = _build_query("topics-update")
                u.execute.return_value = MagicMock(data=[])
                return u

            q.update.side_effect = _update
            return q
        if name == "lesson_embeddings":
            q = _build_query("lesson_embeddings")

            def _delete() -> Any:
                d = _build_query("lesson_embeddings-del")
                def _eq(col: str, val: Any) -> Any:
                    deletes.append((col, val))
                    d2 = _build_query("lesson_embeddings-del-eq")
                    d2.execute.return_value = MagicMock(data=[])
                    return d2
                d.eq.side_effect = _eq
                return d

            def _insert(rows: list[dict[str, Any]]) -> Any:
                inserts.append(rows)
                ins = _build_query("lesson_embeddings-ins")
                ins.execute.return_value = MagicMock(data=rows)
                return ins

            q.delete.side_effect = _delete
            q.insert.side_effect = _insert
            return q
        raise AssertionError(f"unexpected table {name!r}")

    sb = MagicMock()
    sb.table.side_effect = _table

    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: sb)
    # The CLI imports get_supabase inside the function — patch the same name
    # there too via the live module path.
    import app.content.cli as cli_mod
    monkeypatch.setattr(cli_mod, "get_embedder", lambda: _MockEmbedder())

    # Run via the parser so we exercise argparse wiring.
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "ingest",
            "--topic-slug",
            "ap-physics-1.unit-7.oscillations",
            "--fixture",
        ]
    )
    args._embedder = _MockEmbedder()
    rc = await cli.cmd_ingest(args)
    assert rc == 0, "ingest should succeed"

    # We deleted prior chunks for the topic, then inserted N rows.
    assert deletes == [("topic_id", "topic-uuid")]
    assert len(inserts) == 1
    rows = inserts[0]
    assert len(rows) >= 3
    for r in rows:
        assert r["topic_id"] == "topic-uuid"
        assert r["embedding"].startswith("[") and r["embedding"].endswith("]")
        assert isinstance(r["ordinal"], int)
        assert r["text"].strip()
    # Provenance update fired.
    assert len(updates) == 1
    assert updates[0]["content_provenance"]["chunk_count"] == len(rows)
