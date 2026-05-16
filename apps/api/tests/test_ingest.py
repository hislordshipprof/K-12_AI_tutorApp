"""Tests for the teacher-upload ingest pipeline (task 2.1).

Covers the `docs/task-execution.md` 2.1 acceptance criteria:

  * valid PDF / Word / PowerPoint / text are accepted by validation, and
    (LibreOffice present) convert to PDF — `.pdf` is used as-is;
  * an oversized file is rejected by the size cap;
  * a spoofed file (a `.pdf` name with a non-PDF body) is rejected;
  * conversion runs sandboxed (isolated profile dir, hard timeout, scrubbed
    env) — proven by inspecting the `soffice` argv/env;
  * `ingest_material` drives `conversion_status`
    pending -> converting -> converted, and -> failed on a conversion error;
  * the per-teacher ingest rate limit + daily quota gate works.

VALIDATION + status/rate-limit tests need no `soffice` and always run.
Tests that actually invoke LibreOffice SKIP cleanly when `soffice` is not
installed (same pattern as `test_teacher_rls.py` skipping without a DB) —
they run once LibreOffice is present.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.core.rate_limit import RateLimitExceeded, ingest_acquire
from app.pipeline.ingest import (
    ConversionFailed,
    IngestRejected,
    SofficeUnavailable,
    convert_to_pdf,
    find_soffice,
    ingest_material,
    validate_upload,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Conversion tests skip cleanly until LibreOffice is installed.
_HAS_SOFFICE = find_soffice() is not None
_soffice_required = pytest.mark.skipif(
    not _HAS_SOFFICE,
    reason="LibreOffice (soffice) is not installed — office conversion skipped",
)


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ═══ 1. Validation — valid files accepted ═════════════════════════════════
@pytest.mark.parametrize(
    ("name", "expected_type"),
    [
        ("sample.pdf", "pdf"),
        ("sample.docx", "docx"),
        ("sample.pptx", "pptx"),
        ("sample.txt", "txt"),
    ],
)
def test_valid_uploads_pass_validation(name: str, expected_type: str) -> None:
    """Each allow-listed format validates and reports its proven type."""
    result = validate_upload(name, _read(name))
    assert result.file_type == expected_type
    assert result.filename == name
    assert result.size_bytes > 0


def test_valid_upload_with_matching_claimed_mime() -> None:
    """A claimed MIME consistent with the proven content is accepted."""
    result = validate_upload("sample.pdf", _read("sample.pdf"), "application/pdf")
    assert result.file_type == "pdf"
    assert result.mime == "application/pdf"


# ═══ 2. Validation — oversized file rejected ══════════════════════════════
def test_oversized_file_is_rejected() -> None:
    """A file over the size cap is rejected before any type check.

    The limit logic is tested directly — no giant real file needed: one
    byte past `ingest_max_file_mb` MB of (otherwise valid) PDF bytes.
    """
    cap = settings.ingest_max_file_mb * 1024 * 1024
    oversized = b"%PDF-1.4\n" + b"0" * (cap + 1)
    with pytest.raises(IngestRejected) as exc:
        validate_upload("big.pdf", oversized)
    assert exc.value.reason == "too_large"


def test_empty_file_is_rejected() -> None:
    """An empty upload is rejected."""
    with pytest.raises(IngestRejected) as exc:
        validate_upload("empty.pdf", b"")
    assert exc.value.reason == "empty"


# ═══ 3. Validation — spoofed / mismatched types rejected ══════════════════
def test_spoofed_pdf_is_rejected() -> None:
    """A `.pdf`-named file whose body is plain text (no %PDF magic) is
    rejected as a spoofed type — the upload's claimed extension is NOT
    trusted; the sniffed content wins."""
    with pytest.raises(IngestRejected) as exc:
        validate_upload("spoofed.pdf", _read("spoofed.pdf"))
    assert exc.value.reason == "spoofed_content"


def test_docx_renamed_to_pdf_is_rejected() -> None:
    """A real `.docx` (a ZIP) renamed to `.pdf` is caught — the sniffer
    sees a ZIP/docx body under a `.pdf` claim and rejects the mismatch."""
    with pytest.raises(IngestRejected) as exc:
        validate_upload("notreally.pdf", _read("sample.docx"))
    assert exc.value.reason == "spoofed_content"


def test_pptx_renamed_to_docx_is_rejected() -> None:
    """A `.pptx` body under a `.docx` name is rejected — both are ZIPs, so
    the sniffer must peek INSIDE the container to tell them apart."""
    with pytest.raises(IngestRejected) as exc:
        validate_upload("deck.docx", _read("sample.pptx"))
    assert exc.value.reason == "spoofed_content"


def test_disallowed_extension_is_rejected() -> None:
    """A file type not on the allow-list (e.g. `.exe`) is rejected."""
    with pytest.raises(IngestRejected) as exc:
        validate_upload("malware.exe", b"MZ\x90\x00binary")
    assert exc.value.reason == "unknown_extension"


def test_binary_disguised_as_txt_is_rejected() -> None:
    """A binary blob named `.txt` is rejected — text sniffing sees NUL/
    control noise and refuses to call it plain text."""
    with pytest.raises(IngestRejected) as exc:
        validate_upload("fake.txt", b"\x00\x01\x02\x03binary\xff\xfe")
    assert exc.value.reason == "spoofed_content"


def test_claimed_mime_mismatch_is_rejected() -> None:
    """A claimed MIME inconsistent with a (genuinely valid) file is
    rejected — defense in depth alongside the content sniff."""
    with pytest.raises(IngestRejected) as exc:
        validate_upload("sample.pdf", _read("sample.pdf"), "image/png")
    assert exc.value.reason == "mime_mismatch"


# ═══ 4. Conversion — PDF used as-is, office formats convert ═══════════════
def test_pdf_is_used_as_is(tmp_path: Path) -> None:
    """A PDF input is returned unchanged — no LibreOffice call. This path
    needs no soffice, so it always runs."""
    src = tmp_path / "in.pdf"
    src.write_bytes(_read("sample.pdf"))
    out = convert_to_pdf(src)
    assert out == _read("sample.pdf")
    assert out.startswith(b"%PDF")


def test_convert_missing_soffice_raises_when_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `soffice` cannot be found, converting an office file raises a
    distinct `SofficeUnavailable` — never a silent pass."""
    monkeypatch.setattr("app.pipeline.ingest.find_soffice", lambda: None)
    src = tmp_path / "in.docx"
    src.write_bytes(_read("sample.docx"))
    with pytest.raises(SofficeUnavailable):
        convert_to_pdf(src)


@_soffice_required
@pytest.mark.parametrize("name", ["sample.docx", "sample.pptx", "sample.txt"])
def test_office_and_text_convert_to_pdf(name: str, tmp_path: Path) -> None:
    """`.docx` / `.pptx` / `.txt` convert to a real PDF via LibreOffice.

    Skips cleanly when LibreOffice is not installed; runs once it is —
    this is the acceptance criterion 'valid PDF/Word/PPT/text convert'.
    """
    src = tmp_path / name
    src.write_bytes(_read(name))
    out = convert_to_pdf(src)
    assert out.startswith(b"%PDF")
    assert len(out) > 100


def test_conversion_runs_sandboxed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `soffice` invocation is sandboxed — proven by capturing the argv
    + env handed to `subprocess.run`: an isolated per-call profile dir
    (`-env:UserInstallation`), a hard timeout, and a scrubbed environment.

    This does NOT need a real LibreOffice — it stubs `subprocess.run` and
    inspects the call, so it always runs.
    """
    monkeypatch.setattr(
        "app.pipeline.ingest.find_soffice", lambda: "/usr/bin/soffice"
    )
    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str], **kwargs: Any) -> MagicMock:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        # Emulate soffice writing the expected output PDF.
        outdir = Path(argv[argv.index("--outdir") + 1])
        stem = Path(argv[-1]).stem
        (outdir / f"{stem}.pdf").write_bytes(b"%PDF-1.4\nstub\n%%EOF")
        return MagicMock(returncode=0, stderr=b"")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    src = tmp_path / "deck.pptx"
    src.write_bytes(_read("sample.pptx"))
    out = convert_to_pdf(src)
    assert out.startswith(b"%PDF")

    argv = captured["argv"]
    kwargs = captured["kwargs"]
    # (a) headless + an isolated per-call profile dir.
    assert "--headless" in argv
    profile_arg = next(a for a in argv if a.startswith("-env:UserInstallation="))
    assert profile_arg.startswith("-env:UserInstallation=file://")
    # (b) a hard wall-clock timeout is enforced.
    assert kwargs["timeout"] == settings.ingest_convert_timeout_s
    # (c) the environment is scrubbed — no Supabase/Gemini secrets pass through.
    env = kwargs["env"]
    assert "SUPABASE_SERVICE_ROLE_KEY" not in env
    assert "GEMINI_API_KEY" not in env
    assert set(env).issubset(
        {"PATH", "HOME", "SystemRoot", "SystemDrive", "TEMP", "TMP", "USERPROFILE"}
    )


def test_conversion_failure_when_soffice_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero `soffice` exit surfaces as `ConversionFailed`."""
    monkeypatch.setattr(
        "app.pipeline.ingest.find_soffice", lambda: "/usr/bin/soffice"
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: MagicMock(returncode=1, stderr=b"corrupt document"),
    )
    src = tmp_path / "bad.docx"
    src.write_bytes(_read("sample.docx"))
    with pytest.raises(ConversionFailed):
        convert_to_pdf(src)


# ═══ 5. ingest_material — conversion_status transitions ═══════════════════
class _MaterialsTable:
    """Stateful stand-in for `supabase.table("lesson_materials")` — records
    the sequence of `conversion_status` values written so the test can
    assert pending -> converting -> converted (or -> failed)."""

    def __init__(self) -> None:
        self.row: dict[str, Any] = {}
        self.status_history: list[str] = []
        self._mode = ""
        self._payload: dict[str, Any] = {}

    def insert(self, payload: dict[str, Any]) -> _MaterialsTable:
        self._mode = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> _MaterialsTable:
        self._mode = "update"
        self._payload = payload
        return self

    def eq(self, _k: str, _v: Any) -> _MaterialsTable:
        return self

    def execute(self) -> MagicMock:
        if self._mode == "insert":
            self.row = dict(self._payload)
        else:
            self.row.update(self._payload)
        if "conversion_status" in self._payload:
            self.status_history.append(self._payload["conversion_status"])
        return MagicMock(data=[dict(self.row)])


def _make_supabase(materials: _MaterialsTable) -> tuple[MagicMock, MagicMock]:
    """Supabase mock with a stateful `lesson_materials` table + a Storage
    bucket spy. Returns (client, bucket)."""
    bucket = MagicMock(name="bucket")
    storage = MagicMock(name="storage")
    storage.from_.return_value = bucket
    client = MagicMock(name="supabase")
    client.storage = storage
    client.table.side_effect = lambda name: (
        materials if name == "lesson_materials" else MagicMock(name=name)
    )
    return client, bucket


TEACHER_ID = "00000000-0000-0000-0000-000000000001"
UNIT_ID = "33333333-3333-3333-3333-333333333333"


def test_ingest_material_status_pending_converting_converted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid upload walks conversion_status pending -> converting ->
    converted, stores both the original and the normalized PDF, and records
    `normalized_pdf`. Conversion is stubbed so this runs without soffice."""
    materials = _MaterialsTable()
    client, bucket = _make_supabase(materials)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)
    monkeypatch.setattr(
        "app.pipeline.ingest.convert_to_pdf", lambda _p: b"%PDF-1.4\nok\n%%EOF"
    )

    result = ingest_material(
        unit_id=UNIT_ID,
        teacher_id=TEACHER_ID,
        filename="sample.docx",
        data=_read("sample.docx"),
    )

    assert result.conversion_status == "converted"
    assert result.normalized_pdf is not None
    assert materials.status_history == ["pending", "converting", "converted"]
    # The Storage key is prefixed with the teacher's uid (own-prefix RLS).
    assert result.storage_path.startswith(f"{TEACHER_ID}/{UNIT_ID}/")
    # Both the original and the converted PDF were uploaded.
    assert bucket.upload.call_count == 2


def test_ingest_material_marks_failed_on_conversion_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A conversion error lands the row at conversion_status='failed' (so
    the teacher sees it, §13) and the result carries the error — it is not
    raised, and the file never reaches comprehension."""
    materials = _MaterialsTable()
    client, _bucket = _make_supabase(materials)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    def _boom(_p: Any) -> bytes:
        raise ConversionFailed("LibreOffice exited 1: corrupt document")

    monkeypatch.setattr("app.pipeline.ingest.convert_to_pdf", _boom)

    result = ingest_material(
        unit_id=UNIT_ID,
        teacher_id=TEACHER_ID,
        filename="sample.pptx",
        data=_read("sample.pptx"),
    )

    assert result.conversion_status == "failed"
    assert result.normalized_pdf is None
    assert result.error is not None
    assert materials.status_history == ["pending", "converting", "failed"]


def test_ingest_material_rejects_spoofed_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A spoofed upload is rejected by validation BEFORE a row or Storage
    object is created — no `lesson_materials` insert, no upload."""
    materials = _MaterialsTable()
    client, bucket = _make_supabase(materials)
    monkeypatch.setattr("app.core.supabase.get_supabase", lambda: client)

    with pytest.raises(IngestRejected):
        ingest_material(
            unit_id=UNIT_ID,
            teacher_id=TEACHER_ID,
            filename="spoofed.pdf",
            data=_read("spoofed.pdf"),
        )
    assert materials.status_history == []
    bucket.upload.assert_not_called()


# ═══ 6. Per-teacher ingest rate limit + daily quota ═══════════════════════
def test_ingest_rate_limit_blocks_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    """A teacher exceeding `ingest_rate_per_minute` is blocked; a different
    teacher is unaffected (the gate is per-teacher)."""
    monkeypatch.setattr(settings, "ingest_rate_per_minute", 3)
    monkeypatch.setattr(settings, "ingest_quota_per_day", 1000)
    # Reset the in-process window so other tests don't bleed in.
    from app.core import rate_limit as rl

    rl._ingest_events.clear()

    async def _drive() -> None:
        for _ in range(3):
            await ingest_acquire("teacher-A")  # 3 allowed
        with pytest.raises(RateLimitExceeded):
            await ingest_acquire("teacher-A")  # 4th over the limit
        # A different teacher still has a full budget.
        await ingest_acquire("teacher-B")

    asyncio.run(_drive())


def test_ingest_daily_quota_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A teacher exceeding `ingest_quota_per_day` is blocked even when
    under the per-minute rate (the quota is the rolling 24h ceiling)."""
    monkeypatch.setattr(settings, "ingest_rate_per_minute", 1000)
    monkeypatch.setattr(settings, "ingest_quota_per_day", 5)
    from app.core import rate_limit as rl

    rl._ingest_events.clear()

    async def _drive() -> None:
        for _ in range(5):
            await ingest_acquire("teacher-Q")
        with pytest.raises(RateLimitExceeded):
            await ingest_acquire("teacher-Q")

    asyncio.run(_drive())
