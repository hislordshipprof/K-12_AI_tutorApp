"""Segmentation verification script — comprehend a real upload (task 2.2).

Task 2.2 *Verify*: run a segmentation on the `Unit 8 - Fluids` deck and review
the proposed breakdown against its known 8.1-8.4 structure. This script is the
runnable proof that the comprehension core works on a real upload — no HTTP
endpoint, no DB (the segment job that wires the DB path comes later).

Run:
    python -m app.pipeline.segment_script "Unit 8 - Fluids - AP Physics 1.pptx"
    python -m app.pipeline.segment_script <file>... [--kind slides]

It validates + normalizes each file to PDF (reusing task 2.1's `convert_to_pdf`)
then runs `comprehend_unit` — ONE combined multimodal Gemini call — and prints
the proposed topic breakdown plus the page teach/skip summary. A `.pdf` is used
as-is; `.docx`/`.pptx`/`.txt` need LibreOffice installed.

This makes ONE live Gemini call — the orchestrator runs it on the real Fluids
deck to verify the acceptance criteria; the unit tests use a mocked Gemini.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.pipeline.ingest import (
    ConversionFailed,
    IngestRejected,
    SofficeUnavailable,
    convert_to_pdf,
    validate_upload,
)
from app.pipeline.segment import SegmentError, comprehend_unit


def _reconfigure_stdout() -> None:
    """UTF-8 stdout so filenames with unicode render on Windows consoles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


async def run(file_paths: list[str], kind: str) -> int:
    pdfs: list[bytes] = []
    materials: list[dict[str, str]] = []

    for fp in file_paths:
        src = Path(fp)
        if not src.is_file():
            print(f"[segment] file not found: {src}", file=sys.stderr)
            return 2
        data = src.read_bytes()
        try:
            validated = validate_upload(src.name, data)
        except IngestRejected as e:
            print(f"[segment] REJECTED ({e.reason}): {e}", file=sys.stderr)
            return 3
        try:
            pdf_bytes = convert_to_pdf(src)
        except SofficeUnavailable as e:
            print(f"[segment] {e}", file=sys.stderr)
            return 4
        except ConversionFailed as e:
            print(f"[segment] CONVERSION FAILED: {e}", file=sys.stderr)
            return 5
        print(
            f"[segment] {src.name!r}: {validated.file_type} -> "
            f"{len(pdf_bytes)} byte PDF",
            file=sys.stderr,
        )
        pdfs.append(pdf_bytes)
        materials.append({"filename": src.name, "kind": kind})

    print(
        f"[segment] running comprehension on {len(pdfs)} material(s) "
        "(ONE combined multimodal Gemini call)...",
        file=sys.stderr,
    )
    try:
        seg = await comprehend_unit(pdfs, materials)
    except SegmentError as e:
        print(f"[segment] SEGMENTATION FAILED ({e.reason}): {e}", file=sys.stderr)
        return 6

    proposed = seg.proposed
    if proposed.empty_reason:
        print(f"\n[segment] EMPTY breakdown — reason: {proposed.empty_reason}")
        return 0

    teach = sum(1 for p in seg.comprehension.pages if p.teach)
    skip = sum(1 for p in seg.comprehension.pages if not p.teach)
    print(
        f"\n[segment] pages: {teach} teaching, {skip} excluded "
        f"(non-teaching / collapsed animation-build frames)"
    )
    print(f"[segment] proposed {len(proposed.topics)} topic(s):\n")
    for i, t in enumerate(proposed.topics, 1):
        pages = ", ".join(f"m{p.material_idx}:p{p.page_idx}" for p in t.pages)
        print(f"  {i}. {t.title}")
        print(f"     {t.summary}")
        print(f"     pages: [{pages}]")
    if proposed.practice_tags:
        print(f"\n[segment] {len(proposed.practice_tags)} practice question tag(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline.segment_script",
        description="Comprehend + segment a unit's uploads (task 2.2).",
    )
    parser.add_argument("file", nargs="+", help="path(s) to the unit's upload(s)")
    parser.add_argument(
        "--kind",
        default="slides",
        choices=("notes", "slides", "practice"),
        help="the teacher's claimed kind for the upload(s) (a hint to the model)",
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(args.file, args.kind))


if __name__ == "__main__":
    raise SystemExit(main())
