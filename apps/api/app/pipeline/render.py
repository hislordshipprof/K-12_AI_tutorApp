"""Slide rendering — rasterise a topic's claimed pages to PNG (task 2.3).

`teacher-authoring.md` §6 "Render (asset track)": rendering exists ONLY to
*display* the teacher's slides/figures in the classroom — comprehension reads
the PDF directly, and the model can describe a diagram but cannot return its
pixels. So `pymupdf` rasterises to PNG (`material_pages`) only the pages that
will be SHOWN — `slides` and figure-bearing pages, never prose `notes` or
`practice` worksheets. §7: the classroom shows the rendered PNG as a slide
backdrop under Aria's scene-SVG annotations.

Rendering is deferred until *after* the breakdown is confirmed and runs only
for pages a `topic_pages` row actually claims (a topic may pull pages from
more than one material). "notes / practice never rendered" is guaranteed two
ways: prose pages never get a `topic_pages` row at all, AND this renderer
defensively only acts on rows whose `role` is `'slide'` / `'figure'`.

Scope (Phase 2 is backend-only — `CLAUDE.md`): plain service functions, no
HTTP endpoints. This module does NOT build the confirm-breakdown step that
creates `topic_pages` rows — it CONSUMES them. `render_script.py` exercises
the core renderer on a real PDF.

Public API:
    * ``render_pdf_pages`` — pure core: PDF bytes + 0-based page indices ->
      PNG bytes per page. Resolution is config-driven (`settings.render_dpi`).
    * ``render_topic``     — DB function: load a topic's `topic_pages`, render
      each claimed slide/figure page from its material's `normalized_pdf`,
      upload the PNGs to Storage, upsert `material_pages` rows. Idempotent.
    * ``RenderError``      — no rows / missing material / bad page index.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import fitz  # PyMuPDF

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# `topic_pages.role` values this renderer will act on. A topic_pages row only
# ever carries 'slide' / 'figure' (prose notes/practice never get a row at
# all) — but the renderer also filters defensively so a stray role can never
# rasterise a prose page.
RENDERABLE_ROLES = ("slide", "figure")


class RenderError(RuntimeError):
    """Rendering could not run or hit unusable input.

    Carries a stable `reason` code so callers branch without string matching:
      * ``no_pages``      — the topic has no renderable `topic_pages` rows.
      * ``missing_pdf``   — a claimed material has no `normalized_pdf` (it is
                            not yet converted) so its pages cannot render.
      * ``bad_page``      — a claimed `page_idx` is out of the PDF's range.
      * ``no_supabase``   — the DB function needs a Supabase client.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Core — rasterise PDF pages to PNG bytes.
# ─────────────────────────────────────────────────────────────────────────────
def render_pdf_pages(
    pdf: bytes,
    page_indices: list[int],
    *,
    dpi: int | None = None,
) -> dict[int, bytes]:
    """Rasterise the given 0-based PDF pages to PNG bytes.

    The pure core (no DB, no Storage) — `pymupdf` opens the PDF in memory and
    renders each requested page to a PNG at `dpi` (default `settings.render_dpi`,
    ~150 DPI — sharp enough for a full-screen classroom slide backdrop, §7).

    Args:
        pdf: the normalized-PDF bytes of one material.
        page_indices: the 0-based pages to render — duplicates are de-duped so
            a page claimed by two topics rasterises once.
        dpi: raster resolution; falls back to `settings.render_dpi`.

    Returns a `{page_idx: png_bytes}` map. Raises `RenderError('bad_page')` if
    any requested index is outside the PDF.
    """
    resolution = dpi if dpi is not None else settings.render_dpi
    wanted = sorted(set(page_indices))
    if not wanted:
        return {}

    out: dict[int, bytes] = {}
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        page_count = doc.page_count
        for idx in wanted:
            if idx < 0 or idx >= page_count:
                raise RenderError(
                    "bad_page",
                    f"page index {idx} is out of range — the PDF has "
                    f"{page_count} page(s)",
                )
            page = doc.load_page(idx)
            pix = page.get_pixmap(dpi=resolution)
            out[idx] = pix.tobytes("png")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# DB function — render a confirmed topic's claimed pages into Storage.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RenderResult:
    """Outcome of `render_topic` — the pages rendered for this run and the
    pages skipped because they were already rendered (idempotency)."""

    topic_id: str
    rendered: list[str] = field(default_factory=list)  # "<material_id>:<idx>"
    skipped: list[str] = field(default_factory=list)  # already in material_pages


def _png_storage_key(normalized_pdf: str, page_idx: int) -> str:
    """Storage key for a rendered page PNG.

    Reuses the teacher-uid-prefixed convention task 2.1 set for uploads —
    `<teacher-uid>/<unit>/<material>/<file>` — by taking the material's
    `normalized_pdf` key's directory and dropping a `pages/` PNG beside it:
    `<teacher-uid>/<unit>/<material>/pages/<idx>.png`. Keeping the same
    teacher-uid prefix means the bucket's own-prefix RLS still admits it.
    """
    parent = PurePosixPath(normalized_pdf).parent
    return str(parent / "pages" / f"{page_idx}.png")


async def render_topic(
    topic_id: str,
    *,
    dpi: int | None = None,
) -> RenderResult:
    """Render a confirmed topic's claimed slide/figure pages to PNGs.

    The flow (`teacher-authoring.md` §6 "Render"):

      1. Load the topic's `topic_pages` rows; keep only `role in
         ('slide','figure')` (defensive — prose pages never get a row, this
         also drops a stray non-renderable role). No renderable rows raises
         `RenderError('no_pages')`.
      2. For each DISTINCT `(material_id, page_idx)` claimed, fetch that
         material's `normalized_pdf` from the `lesson-materials` bucket,
         rasterise the page (`render_pdf_pages`), and upload the PNG to
         Storage under the teacher-uid prefix.
      3. **Upsert** a `material_pages` row `(material_id, idx, image_path)`.

    Idempotent: `material_pages`' PK is `(material_id, idx)`. A page already
    present in `material_pages` is SKIPPED (not re-rendered, not duplicated),
    so a second `render_topic` run — or two topics claiming the same page —
    renders that page exactly once. PDFs are downloaded and opened at most
    once per material.

    Returns a `RenderResult`. Requires a configured Supabase service-role
    client (reads `topic_pages` + `lesson_materials`, reads/writes Storage,
    upserts `material_pages`).
    """
    from app.core.supabase import get_supabase

    supabase = get_supabase()
    if supabase is None:
        raise RenderError(
            "no_supabase",
            "render_topic requires Supabase to be configured "
            "(SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)",
        )

    # 1. Load the topic's claimed pages — only slide/figure roles render.
    resp = (
        supabase.table("topic_pages")
        .select("material_id,page_idx,role")
        .eq("topic_id", topic_id)
        .execute()
    )
    rows: list[dict[str, Any]] = list(getattr(resp, "data", None) or [])
    renderable = [r for r in rows if r.get("role") in RENDERABLE_ROLES]
    if not renderable:
        raise RenderError(
            "no_pages",
            f"topic {topic_id} has no slide/figure topic_pages to render",
        )

    # Distinct (material_id, page_idx) — two topic_pages rows / two topics may
    # claim the same page; it must render only once.
    wanted: dict[str, set[int]] = {}
    for r in renderable:
        mid = str(r["material_id"])
        wanted.setdefault(mid, set()).add(int(r["page_idx"]))

    # Pages already in material_pages — skip them (idempotency).
    already = (
        supabase.table("material_pages")
        .select("material_id,idx")
        .in_("material_id", list(wanted))
        .execute()
    )
    rendered_already: dict[str, set[int]] = {}
    for r in list(getattr(already, "data", None) or []):
        rendered_already.setdefault(str(r["material_id"]), set()).add(int(r["idx"]))

    bucket = supabase.storage.from_("lesson-materials")
    result = RenderResult(topic_id=topic_id)

    for material_id, page_set in wanted.items():
        todo = sorted(page_set - rendered_already.get(material_id, set()))
        for idx in sorted(page_set):
            if idx not in todo:
                result.skipped.append(f"{material_id}:{idx}")
        if not todo:
            continue

        # Resolve the material's normalized PDF key.
        mat = (
            supabase.table("lesson_materials")
            .select("normalized_pdf")
            .eq("id", material_id)
            .single()
            .execute()
        )
        mat_row = getattr(mat, "data", None) or {}
        normalized_pdf = mat_row.get("normalized_pdf")
        if not normalized_pdf:
            raise RenderError(
                "missing_pdf",
                f"material {material_id} has no normalized_pdf — it cannot "
                "be rendered (not converted)",
            )

        # Download + rasterise the not-yet-rendered pages, once per material.
        pdf_bytes = bucket.download(normalized_pdf)
        pngs = render_pdf_pages(pdf_bytes, todo, dpi=dpi)

        for idx in todo:
            png = pngs[idx]
            key = _png_storage_key(normalized_pdf, idx)
            bucket.upload(
                key,
                io.BytesIO(png).getvalue(),
                {"content-type": "image/png", "upsert": "true"},
            )
            # Upsert — the PK is (material_id, idx); a concurrent first
            # render of the same page resolves to one row, never an error.
            supabase.table("material_pages").upsert(
                {"material_id": material_id, "idx": idx, "image_path": key},
                on_conflict="material_id,idx",
            ).execute()
            result.rendered.append(f"{material_id}:{idx}")

    log.info(
        "render_topic_ok",
        topic_id=topic_id,
        rendered=len(result.rendered),
        skipped=len(result.skipped),
    )
    return result


__all__ = [
    "RenderError",
    "RenderResult",
    "RENDERABLE_ROLES",
    "render_pdf_pages",
    "render_topic",
]
