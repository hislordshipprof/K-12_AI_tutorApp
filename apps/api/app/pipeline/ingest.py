"""Teacher-upload ingest: validate untrusted files, normalize to PDF.

`teacher-authoring.md` §6 "Ingest" + "Normalize -> PDF": teacher uploads are
*untrusted files*. Before anything downstream touches them this module:

1. **Validates** — a per-file size cap, a MIME allow-list (PDF / Word /
   PowerPoint / plain text), and **spoofed-type rejection** by content
   sniffing (a file whose real bytes disagree with its claimed type is
   rejected, not trusted).
2. **Normalizes to PDF** — the universal intermediate every later stage
   reads. PDF is used as-is; `.docx` / `.pptx` / `.txt` are converted via a
   server-side **LibreOffice headless** step, run **sandboxed** (hard
   timeout, isolated per-call profile dir, clean environment).
3. **Drives `conversion_status`** — `ingest_material` writes the
   `lesson_materials` row (`pending`), uploads the original to Storage,
   converts (`converting`), and on success uploads the PDF and sets
   `converted`; any failure lands `failed`.

This is a Phase 2.1 building block — there are no HTTP endpoints here. The
segment job (task 2.2) calls `ingest_material`; the verification script
(`app/pipeline/ingest_script.py`) exercises it on a real file.

LibreOffice (`soffice`) is installed by the Docker layer in `apps/api/
Dockerfile`. When `soffice` is absent (local dev before install) the
validation path still works fully; only the conversion of office formats
raises `SofficeUnavailable`.
"""

from __future__ import annotations

import datetime as _dt
import io
import os
import shutil
import subprocess  # noqa: S404 — soffice is invoked with a fixed, non-shell argv
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# ── Allow-listed upload types ────────────────────────────────────────────────
# Map a logical kind -> (its canonical MIME, accepted file extensions). Only
# these four are accepted; anything else is rejected at validation.
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
TXT_MIME = "text/plain"

# Extension -> the canonical type label this module uses internally.
_EXT_TO_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".txt": "txt",
}

# Canonical type label -> the MIME stored on the lesson_materials row.
_TYPE_TO_MIME: dict[str, str] = {
    "pdf": PDF_MIME,
    "docx": DOCX_MIME,
    "pptx": PPTX_MIME,
    "txt": TXT_MIME,
}

# Claimed MIME strings we accept as matching each type (clients vary).
_TYPE_TO_ACCEPTED_MIMES: dict[str, set[str]] = {
    "pdf": {PDF_MIME},
    "docx": {DOCX_MIME, "application/zip"},
    "pptx": {PPTX_MIME, "application/zip"},
    "txt": {TXT_MIME},
}


class IngestRejected(ValueError):
    """An upload failed validation — size, type, or a spoofed/mismatched body.

    Carries a stable `reason` code so callers can branch without string
    matching: 'too_large' | 'unknown_extension' | 'mime_mismatch' |
    'spoofed_content' | 'empty'.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class SofficeUnavailable(RuntimeError):
    """`soffice`/`libreoffice` is not installed — office conversion cannot run.

    Distinct from a conversion *failure*: this means the tool is missing
    from the host (local dev before LibreOffice install). In the Docker
    image the LibreOffice layer guarantees it is present.
    """


class ConversionFailed(RuntimeError):
    """LibreOffice ran but did not produce a PDF (corrupt file, timeout)."""


@dataclass(frozen=True)
class ValidatedUpload:
    """The result of `validate_upload` — a file proven safe to convert."""

    file_type: str  # 'pdf' | 'docx' | 'pptx' | 'txt'
    mime: str  # canonical MIME for the lesson_materials row
    filename: str
    size_bytes: int


# ─────────────────────────────────────────────────────────────────────────────
# 1. Validation — size cap, MIME allow-list, spoofed-type rejection
# ─────────────────────────────────────────────────────────────────────────────
def _sniff_type(data: bytes) -> str | None:
    """Identify a file's REAL type from its content (magic bytes).

    This is the spoof defense — it ignores the claimed extension/MIME and
    inspects the bytes:

      * PDF        -> starts with the `%PDF` signature.
      * `.docx`    -> a ZIP container (`PK\\x03\\x04`) whose entries include
                      `word/` (the OOXML Word part) or a Word content-type.
      * `.pptx`    -> a ZIP container whose entries include `ppt/`.
      * `.txt`     -> decodes as UTF-8/Latin-1 text with no NUL/binary noise.

    Returns the canonical type label, or None when nothing matches (the
    caller rejects an unidentifiable file). `python-magic`/`libmagic` is
    deliberately NOT used — it is an extra system dependency; these four
    formats have unambiguous, cheap-to-check signatures.
    """
    if not data:
        return None

    # PDF — the %PDF signature is within the first bytes.
    if data[:5].startswith(b"%PDF"):
        return "pdf"

    # OOXML (.docx/.pptx) — a ZIP whose internal layout names the format.
    if data[:4] == b"PK\x03\x04":
        return _sniff_ooxml(data)

    # Plain text — must decode cleanly and carry no binary control noise.
    if _looks_like_text(data):
        return "txt"

    return None


def _sniff_ooxml(data: bytes) -> str | None:
    """Peek inside a ZIP container to tell a `.docx` from a `.pptx`.

    Both are ZIPs, so the `PK` magic alone is ambiguous. OOXML packages
    have a fixed internal layout: a Word document has a `word/` directory,
    a PowerPoint deck has a `ppt/` directory, and `[Content_Types].xml`
    names the part types. We read the central directory (no extraction)
    and decide. A ZIP that is neither is rejected (returns None).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if any(n.startswith("ppt/") for n in names):
                return "pptx"
            if any(n.startswith("word/") for n in names):
                return "docx"
            # Fall back to [Content_Types].xml when the dir layout is odd.
            if "[Content_Types].xml" in names:
                ctypes = zf.read("[Content_Types].xml").decode(
                    "utf-8", errors="ignore"
                )
                if "presentationml" in ctypes:
                    return "pptx"
                if "wordprocessingml" in ctypes:
                    return "docx"
    except (zipfile.BadZipFile, OSError, KeyError):
        return None
    return None


def _looks_like_text(data: bytes) -> bool:
    """True when `data` is plausibly a plain-text file, not a binary blob.

    A real `.txt` decodes as UTF-8 (or Latin-1) and contains no NUL bytes
    and only a small fraction of non-printable control characters. A
    binary file mislabelled `.txt` fails one of these.
    """
    if b"\x00" in data:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError:
            return False
    # Allow the usual whitespace controls; count anything else as noise.
    allowed_controls = {"\t", "\n", "\r", "\f", "\v"}
    noise = sum(
        1 for ch in text if ord(ch) < 32 and ch not in allowed_controls
    )
    return noise <= max(1, len(text) // 100)


def validate_upload(
    filename: str,
    data: bytes,
    claimed_mime: str | None = None,
) -> ValidatedUpload:
    """Validate an untrusted upload — raise `IngestRejected` if unsafe.

    Enforces, in order:
      1. **Size cap** — at most `settings.ingest_max_file_mb` MB; empty
         files are rejected.
      2. **Extension allow-list** — the filename extension must be one of
         `.pdf` / `.docx` / `.pptx` / `.txt`.
      3. **Spoofed-type rejection** — the file's REAL type (sniffed from
         its bytes, `_sniff_type`) must match the claimed extension. A
         `.pdf`-named file that is actually a ZIP, or a text file with an
         executable body, is rejected here. The claimed `mime` (when
         given) must also be consistent with the sniffed type.

    Returns a `ValidatedUpload` whose `mime` is the canonical MIME (derived
    from the proven content, never the spoofable claim).
    """
    size = len(data)
    cap = settings.ingest_max_file_mb * 1024 * 1024
    if size == 0:
        raise IngestRejected("empty", "upload is empty")
    if size > cap:
        raise IngestRejected(
            "too_large",
            f"file is {size} bytes; the cap is "
            f"{settings.ingest_max_file_mb} MB ({cap} bytes)",
        )

    ext = Path(filename).suffix.lower()
    claimed_type = _EXT_TO_TYPE.get(ext)
    if claimed_type is None:
        raise IngestRejected(
            "unknown_extension",
            f"extension {ext!r} is not allowed — accept only "
            f"{sorted(_EXT_TO_TYPE)}",
        )

    sniffed = _sniff_type(data)
    if sniffed is None:
        raise IngestRejected(
            "spoofed_content",
            f"{filename!r} claims {ext} but its content is not a "
            "recognised PDF / Word / PowerPoint / text file",
        )
    if sniffed != claimed_type:
        raise IngestRejected(
            "spoofed_content",
            f"{filename!r} claims {ext} but its content is a "
            f"{sniffed!r} file — rejected as a spoofed type",
        )

    # The claimed MIME, when supplied, must agree with the proven type.
    if claimed_mime:
        normalized = claimed_mime.split(";")[0].strip().lower()
        if normalized not in _TYPE_TO_ACCEPTED_MIMES[claimed_type]:
            raise IngestRejected(
                "mime_mismatch",
                f"claimed MIME {claimed_mime!r} does not match a "
                f"{claimed_type} upload",
            )

    return ValidatedUpload(
        file_type=claimed_type,
        mime=_TYPE_TO_MIME[claimed_type],
        filename=filename,
        size_bytes=size,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Normalize -> PDF (LibreOffice headless, sandboxed)
# ─────────────────────────────────────────────────────────────────────────────
def find_soffice() -> str | None:
    """Locate the LibreOffice headless executable, or return None.

    Resolution covers both hosts:
      * Linux / the Docker image — `soffice` or `libreoffice` on PATH.
      * Windows (local dev) — `soffice.com` (the CLI front-end, preferred
        for headless use) or `soffice.exe`, on PATH or the default
        `Program Files` install location.

    Returns None when LibreOffice is not installed — callers translate
    that into `SofficeUnavailable` so conversion tests can skip cleanly.
    """
    for name in ("soffice", "soffice.com", "soffice.exe", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found

    # Windows default install paths — `shutil.which` misses these when the
    # installer did not add LibreOffice to PATH.
    if os.name == "nt":
        for base in (
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        ):
            candidate = Path(base) / "LibreOffice" / "program" / "soffice.com"
            if candidate.exists():
                return str(candidate)
    return None


def convert_to_pdf(src_path: str | Path) -> bytes:
    """Normalize one validated file to PDF bytes — the universal form.

    * `.pdf`  -> returned as-is (no conversion).
    * `.docx` / `.pptx` / `.txt` -> converted via LibreOffice headless.

    LibreOffice handles `.txt` too, so ONE code path covers all three
    office/text formats — no separate text-to-PDF library is pulled in
    (the project rule: do not add abstractions the task does not need).

    **Sandboxing** (`teacher-authoring.md` §6 — uploads are untrusted):
      * a hard wall-clock **timeout** (`settings.ingest_convert_timeout_s`)
        kills a soffice that hangs on a malformed file;
      * a fresh, **isolated per-call LibreOffice profile dir** via
        `-env:UserInstallation` so a crafted file cannot poison a shared
        profile or leak state between conversions;
      * a **minimal, scrubbed environment** — only `PATH`/`HOME` are kept,
        so the subprocess inherits no secrets from the API process;
      * the argv is fixed and `shell=False`, so a filename cannot inject.
      * Network isolation and CPU/memory limits come from the Docker layer
        the conversion runs inside (documented in `apps/api/Dockerfile`).

    Raises `SofficeUnavailable` if LibreOffice is not installed, or
    `ConversionFailed` if it ran but produced no PDF.
    """
    src = Path(src_path)
    if not src.is_file():
        raise ConversionFailed(f"source file does not exist: {src}")

    if src.suffix.lower() == ".pdf":
        # PDF is the universal form already — used as-is, no conversion.
        return src.read_bytes()

    soffice = find_soffice()
    if soffice is None:
        raise SofficeUnavailable(
            "LibreOffice (soffice) is not installed — office/text "
            "conversion is unavailable. The Docker image installs it; "
            "for local dev install LibreOffice."
        )

    with tempfile.TemporaryDirectory(prefix="ingest-convert-") as workdir:
        out_dir = Path(workdir) / "out"
        out_dir.mkdir()
        profile_dir = Path(workdir) / "profile"
        profile_dir.mkdir()

        # Per-call isolated profile — `-env:UserInstallation` must be a
        # file:// URI. A crafted file cannot reach a shared/global profile.
        profile_uri = profile_dir.resolve().as_uri()
        argv = [
            soffice,
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--nologo",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(src.resolve()),
        ]

        # Scrubbed environment — pass only what soffice needs to start, so
        # the subprocess inherits none of the API process's secrets.
        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(profile_dir),
        }
        if os.name == "nt":
            # Windows soffice needs these to locate system libraries/profile.
            for key in ("SystemRoot", "SystemDrive", "TEMP", "TMP", "USERPROFILE"):
                if key in os.environ:
                    clean_env[key] = os.environ[key]

        try:
            proc = subprocess.run(  # noqa: S603 — fixed argv, shell=False
                argv,
                capture_output=True,
                timeout=settings.ingest_convert_timeout_s,
                env=clean_env,
                cwd=workdir,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ConversionFailed(
                f"LibreOffice conversion timed out after "
                f"{settings.ingest_convert_timeout_s}s"
            ) from e

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="ignore")[:500]
            raise ConversionFailed(
                f"LibreOffice exited {proc.returncode}: {stderr}"
            )

        # soffice names the output `<stem>.pdf` in --outdir.
        pdf_path = out_dir / f"{src.stem}.pdf"
        if not pdf_path.is_file():
            produced = [p.name for p in out_dir.iterdir()]
            raise ConversionFailed(
                f"LibreOffice produced no PDF (out dir: {produced})"
            )
        return pdf_path.read_bytes()


# ─────────────────────────────────────────────────────────────────────────────
# 3. The conversion_status service — validate -> store -> convert -> store
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class IngestResult:
    """Outcome of `ingest_material` — the persisted lesson_materials row id
    and its terminal `conversion_status`."""

    material_id: str
    conversion_status: str  # 'converted' | 'failed'
    storage_path: str
    normalized_pdf: str | None
    error: str | None = None


def _storage_key(teacher_id: str, unit_id: str, material_id: str, name: str) -> str:
    """Build a Storage object key. §10 / task 1.3: the first segment is the
    uploading teacher's uid so the bucket's own-prefix RLS policy admits it
    (`<teacher-uuid>/<unit>/<material>/<file>`)."""
    return f"{teacher_id}/{unit_id}/{material_id}/{name}"


def ingest_material(
    *,
    unit_id: str,
    teacher_id: str,
    filename: str,
    data: bytes,
    claimed_mime: str | None = None,
    kind: str = "notes",
) -> IngestResult:
    """Ingest one teacher upload end-to-end and model `conversion_status`.

    The flow (`teacher-authoring.md` §4 `lesson_materials`, §6 "Ingest"):

      1. **Validate** the untrusted bytes (`validate_upload`) — a rejection
         raises `IngestRejected` BEFORE any row or Storage object exists.
      2. Write the `lesson_materials` row with `conversion_status='pending'`.
      3. Upload the original file to the `lesson-materials` Storage bucket
         under the teacher's prefix; record `storage_path`.
      4. Flip `conversion_status='converting'` and run `convert_to_pdf`.
      5. On success: upload the PDF, set `normalized_pdf` +
         `conversion_status='converted'`.
         On any failure: set `conversion_status='failed'` + `error`; the
         file never reaches comprehension (§13 corrupt-upload rule).

    Requires a configured Supabase service-role client (Storage + the
    `lesson_materials` table). Returns an `IngestResult`; a conversion
    failure is reported in the result (status `'failed'`), not raised — the
    teacher needs to see a `failed` row, per §13.
    """
    from app.core.supabase import get_supabase

    # 1. Validate FIRST — a bad upload produces no row and no Storage object.
    validated = validate_upload(filename, data, claimed_mime)

    supabase = get_supabase()
    if supabase is None:
        raise RuntimeError(
            "ingest_material requires Supabase to be configured "
            "(SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)"
        )

    material_id = str(uuid.uuid4())
    now = _dt.datetime.now(_dt.UTC).isoformat()
    storage_path = _storage_key(teacher_id, unit_id, material_id, validated.filename)
    bucket = supabase.storage.from_("lesson-materials")

    # 2. Persist the row up front — `pending`. A crash after this leaves a
    #    visible row the teacher / a retry can see, not a silent void.
    supabase.table("lesson_materials").insert(
        {
            "id": material_id,
            "unit_id": unit_id,
            "kind": kind,
            "storage_path": storage_path,
            "filename": validated.filename,
            "mime": validated.mime,
            "conversion_status": "pending",
            "uploaded_by": teacher_id,
            "uploaded_at": now,
        }
    ).execute()

    def _set_status(status: str, extra: dict[str, object] | None = None) -> None:
        supabase.table("lesson_materials").update(
            {"conversion_status": status, **(extra or {})}
        ).eq("id", material_id).execute()

    try:
        # 3. Store the original upload under the teacher's own prefix.
        bucket.upload(
            storage_path,
            data,
            {"content-type": validated.mime, "upsert": "true"},
        )

        # 4. converting -> run the sandboxed normalize-to-PDF step.
        _set_status("converting")
        with tempfile.TemporaryDirectory(prefix="ingest-src-") as srcdir:
            src_file = Path(srcdir) / validated.filename
            src_file.write_bytes(data)
            pdf_bytes = convert_to_pdf(src_file)

        # 5. Store the normalized PDF and mark the row converted.
        pdf_key = _storage_key(
            teacher_id, unit_id, material_id, f"{Path(validated.filename).stem}.pdf"
        )
        bucket.upload(
            pdf_key,
            pdf_bytes,
            {"content-type": PDF_MIME, "upsert": "true"},
        )
        _set_status("converted", {"normalized_pdf": pdf_key})
        log.info(
            "ingest_material_converted",
            material_id=material_id,
            unit_id=unit_id,
            file_type=validated.file_type,
        )
        return IngestResult(
            material_id=material_id,
            conversion_status="converted",
            storage_path=storage_path,
            normalized_pdf=pdf_key,
        )
    except Exception as e:  # noqa: BLE001 — any failure must land 'failed'
        log.warning(
            "ingest_material_failed",
            material_id=material_id,
            unit_id=unit_id,
            error=str(e),
        )
        _set_status("failed")
        return IngestResult(
            material_id=material_id,
            conversion_status="failed",
            storage_path=storage_path,
            normalized_pdf=None,
            error=str(e),
        )


__all__ = [
    "IngestRejected",
    "SofficeUnavailable",
    "ConversionFailed",
    "ValidatedUpload",
    "IngestResult",
    "validate_upload",
    "convert_to_pdf",
    "find_soffice",
    "ingest_material",
    "PDF_MIME",
    "DOCX_MIME",
    "PPTX_MIME",
    "TXT_MIME",
]
