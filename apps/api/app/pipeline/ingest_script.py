"""Ingest verification script — run a real file through validate + convert.

Task 2.1 *Verify*: run on `Unit 8 - Fluids - AP Physics 1.pptx`. This is the
runnable proof that the ingest building blocks work on a real upload — no
HTTP endpoint, no DB needed (the segment job in 2.2 wires the DB path).

Run:
    python -m app.pipeline.ingest_script "Unit 8 - Fluids - AP Physics 1.pptx"
    python -m app.pipeline.ingest_script <file> --out fluids.pdf

It validates the file (size cap, MIME allow-list, spoof sniffing), converts
it to PDF in memory, and prints a result. With `--out` it also writes the
PDF so you can open it. Conversion of `.docx`/`.pptx`/`.txt` needs
LibreOffice installed; a missing `soffice` is reported, not a crash.

The script is a thin orchestration layer — the real work is in
`app.pipeline.ingest`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.pipeline.ingest import (
    ConversionFailed,
    IngestRejected,
    SofficeUnavailable,
    convert_to_pdf,
    find_soffice,
    validate_upload,
)


def _reconfigure_stdout() -> None:
    """UTF-8 stdout so filenames with unicode render on Windows consoles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def run(file_path: str, out_path: str | None) -> int:
    src = Path(file_path)
    if not src.is_file():
        print(f"[ingest] file not found: {src}", file=sys.stderr)
        return 2

    data = src.read_bytes()

    # 1. Validate the untrusted upload.
    try:
        validated = validate_upload(src.name, data)
    except IngestRejected as e:
        print(f"[ingest] REJECTED ({e.reason}): {e}", file=sys.stderr)
        return 3
    print(
        f"[ingest] validated: type={validated.file_type} "
        f"mime={validated.mime} size={validated.size_bytes} bytes",
        file=sys.stderr,
    )

    # 2. Normalize to PDF.
    soffice = find_soffice()
    if validated.file_type != "pdf" and soffice is None:
        print(
            "[ingest] LibreOffice (soffice) is not installed — cannot "
            "convert office/text formats. Install LibreOffice and re-run.",
            file=sys.stderr,
        )
        return 4
    if soffice:
        print(f"[ingest] using soffice: {soffice}", file=sys.stderr)

    try:
        pdf_bytes = convert_to_pdf(src)
    except SofficeUnavailable as e:
        print(f"[ingest] {e}", file=sys.stderr)
        return 4
    except ConversionFailed as e:
        print(f"[ingest] CONVERSION FAILED: {e}", file=sys.stderr)
        return 5

    if not pdf_bytes.startswith(b"%PDF"):
        print("[ingest] output is not a valid PDF", file=sys.stderr)
        return 6

    print(
        f"[ingest] OK — produced a {len(pdf_bytes)} byte PDF "
        f"from {src.name!r}",
        file=sys.stderr,
    )
    if out_path:
        Path(out_path).write_bytes(pdf_bytes)
        print(f"[ingest] wrote PDF -> {out_path}", file=sys.stderr)

    print(f"pdf_bytes={len(pdf_bytes)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline.ingest_script",
        description="Validate + normalize one teacher upload to PDF (task 2.1).",
    )
    parser.add_argument("file", help="path to the upload to ingest")
    parser.add_argument(
        "--out",
        help="optional path to write the converted PDF to",
        default=None,
    )
    args = parser.parse_args(argv)
    return run(args.file, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
