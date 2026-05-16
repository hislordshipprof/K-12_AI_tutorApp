"""Slide-render verification script — rasterise real PDF pages (task 2.3).

Task 2.3 *Verify*: confirm a Fluids breakdown and check the rendered PNGs.
This script is the runnable proof that the renderer works on a real PDF — no
HTTP endpoint, no DB (the confirm-breakdown step that writes `topic_pages`
rows comes in a later task). It renders given pages straight from a PDF and
reports each PNG's size + validity.

Run:
    python -m app.pipeline.render_script fluids.pdf --pages 4 5 6
    python -m app.pipeline.render_script fluids.pdf --pages 0 --out-dir out

It opens the PDF, rasterises the requested 0-based pages via `pymupdf` (the
same `render_pdf_pages` core the DB path uses), and prints the byte size of
each PNG. With `--out-dir` it also writes the PNGs so you can open them.

The real work is in `app.pipeline.render`; this is a thin orchestration shell.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.pipeline.render import RenderError, render_pdf_pages


def _reconfigure_stdout() -> None:
    """UTF-8 stdout so filenames with unicode render on Windows consoles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def run(pdf_path: str, pages: list[int], out_dir: str | None) -> int:
    src = Path(pdf_path)
    if not src.is_file():
        print(f"[render] file not found: {src}", file=sys.stderr)
        return 2

    data = src.read_bytes()
    if not data.startswith(b"%PDF"):
        print(f"[render] {src.name!r} is not a PDF", file=sys.stderr)
        return 3

    print(
        f"[render] rasterising {len(pages)} page(s) of {src.name!r}...",
        file=sys.stderr,
    )
    try:
        pngs = render_pdf_pages(data, pages)
    except RenderError as e:
        print(f"[render] RENDER FAILED ({e.reason}): {e}", file=sys.stderr)
        return 4

    out_path = Path(out_dir) if out_dir else None
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)

    ok = True
    for idx in sorted(pngs):
        png = pngs[idx]
        valid = png.startswith(b"\x89PNG\r\n\x1a\n")
        ok = ok and valid
        print(f"  page {idx}: {len(png)} bytes  PNG={'ok' if valid else 'INVALID'}")
        if out_path is not None:
            dest = out_path / f"page-{idx}.png"
            dest.write_bytes(png)
            print(f"    wrote {dest}", file=sys.stderr)

    print(f"pages_rendered={len(pngs)}")
    return 0 if ok else 5


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline.render_script",
        description="Rasterise PDF pages to PNG (task 2.3 slide rendering).",
    )
    parser.add_argument("pdf", help="path to the normalized PDF")
    parser.add_argument(
        "--pages",
        type=int,
        nargs="+",
        required=True,
        help="0-based page indices to render",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="optional directory to write the rendered PNGs to",
    )
    args = parser.parse_args(argv)
    return run(args.pdf, args.pages, args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
