"""Build the tiny ingest-test fixtures — stdlib only, no python-docx/pptx.

Task 2.1 needs small sample uploads for the validation + (skip-guarded)
conversion tests:

  * `sample.pdf`   — a minimal one-page PDF.
  * `sample.txt`   — plain text.
  * `sample.docx`  — a minimal valid OOXML Word package.
  * `sample.pptx`  — a minimal valid OOXML PowerPoint package.
  * `spoofed.pdf`  — a `.pdf`-named file whose body is actually plain text
                     (the spoof-rejection fixture).

`.docx`/`.pptx` are just ZIP containers with a fixed OOXML part layout, so
we build them with `zipfile` — avoiding the python-docx / python-pptx
dependencies the task does not otherwise need. The packages are minimal but
real: the `[Content_Types].xml` + `_rels` + `word/`/`ppt/` parts are enough
for LibreOffice headless to open and convert them, and for the sniffer to
identify them.

This script is committed alongside the fixtures so they can be regenerated
deterministically. Run once:  python tests/fixtures/_build_fixtures.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


# ── PDF ──────────────────────────────────────────────────────────────────────
def _minimal_pdf() -> bytes:
    """A hand-built one-page PDF — valid enough to parse and to be used as-is."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 58 >>\nstream\nBT /F1 18 Tf 72 720 Td "
        b"(Fluids ingest test) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n".encode()
        + f"startxref\n{xref_pos}\n%%EOF".encode()
    )
    return bytes(out)


# ── OOXML helpers ────────────────────────────────────────────────────────────
def _write_zip(path: Path, parts: dict[str, str | bytes]) -> None:
    """Write an OOXML ZIP package. `[Content_Types].xml` must be first."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Content types first — required by the OOXML spec.
        zf.writestr("[Content_Types].xml", parts["[Content_Types].xml"])
        for name, content in parts.items():
            if name == "[Content_Types].xml":
                continue
            zf.writestr(name, content)


def _docx_parts() -> dict[str, str]:
    ns_ct = "http://schemas.openxmlformats.org/package/2006/content-types"
    ns_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    ns_w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    return {
        "[Content_Types].xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Types xmlns="{ns_ct}">'
            f'<Default Extension="rels" ContentType="application/'
            f'vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/word/document.xml" ContentType='
            f'"application/vnd.openxmlformats-officedocument.'
            f'wordprocessingml.document.main+xml"/></Types>'
        ),
        "_rels/.rels": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{ns_rel}">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org'
            f'/officeDocument/2006/relationships/officeDocument" '
            f'Target="word/document.xml"/></Relationships>'
        ),
        "word/document.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{ns_w}"><w:body>'
            f"<w:p><w:r><w:t>Fluids unit ingest test document.</w:t>"
            f"</w:r></w:p></w:body></w:document>"
        ),
    }


def _pptx_parts() -> dict[str, str]:
    ns_ct = "http://schemas.openxmlformats.org/package/2006/content-types"
    ns_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    return {
        "[Content_Types].xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Types xmlns="{ns_ct}">'
            f'<Default Extension="rels" ContentType="application/'
            f'vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/ppt/presentation.xml" ContentType='
            f'"application/vnd.openxmlformats-officedocument.'
            f'presentationml.presentation.main+xml"/>'
            f'<Override PartName="/ppt/slides/slide1.xml" ContentType='
            f'"application/vnd.openxmlformats-officedocument.'
            f'presentationml.slide+xml"/></Types>'
        ),
        "_rels/.rels": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{ns_rel}">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org'
            f'/officeDocument/2006/relationships/officeDocument" '
            f'Target="ppt/presentation.xml"/></Relationships>'
        ),
        "ppt/presentation.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:presentation xmlns:p="{ns_p}" xmlns:r="{ns_r}">'
            f'<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>'
            f'<p:sldSz cx="9144000" cy="6858000"/></p:presentation>'
        ),
        "ppt/_rels/presentation.xml.rels": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{ns_rel}">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org'
            f'/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide1.xml"/></Relationships>'
        ),
        "ppt/slides/slide1.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:sld xmlns:p="{ns_p}" xmlns:a="{ns_a}">'
            f"<p:cSld><p:spTree></p:spTree></p:cSld></p:sld>"
        ),
    }


def main() -> None:
    (HERE / "sample.pdf").write_bytes(_minimal_pdf())
    (HERE / "sample.txt").write_text(
        "Fluids unit ingest test.\nDensity, pressure, buoyancy.\n",
        encoding="utf-8",
    )
    _write_zip(HERE / "sample.docx", _docx_parts())
    _write_zip(HERE / "sample.pptx", _pptx_parts())
    # The spoof fixture — named .pdf, body is plain text (no %PDF magic).
    (HERE / "spoofed.pdf").write_bytes(
        b"This is not really a PDF. It is plain text wearing a .pdf name."
    )
    print("fixtures written to", HERE)


if __name__ == "__main__":
    main()
