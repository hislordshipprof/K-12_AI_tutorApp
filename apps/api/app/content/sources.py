"""Source-book metadata + URL resolution for the content pipeline.

`mapping.yaml` keys topic slugs to lists of section refs like
``openstax/college-physics-2e/ch-16/16-1``. This module turns those refs into
fetchable HTTPS URLs and surfaces the per-book license metadata for
attribution.

OpenStax serves both:
  - A reader page (``/books/<book>/pages/<page>``) — friendly HTML.
  - A CNX archive endpoint (``/api/v0/contents/<uuid>.html``) — cleaner HTML
    but per-section UUIDs change. We use the reader URL by default because
    section anchors (``ch-16/16-1``) map cleanly to readable page slugs.

The mapping is data, not code; this module is pure resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
MAPPING_PATH = HERE / "mapping.yaml"


@dataclass(frozen=True)
class BookMeta:
    """Per-book licensing + URL template metadata."""

    slug: str
    title: str
    license: str
    attribution: str
    reader_base: str  # e.g. https://openstax.org/books/college-physics-2e/pages/

    def page_url(self, page_slug: str) -> str:
        """Build a reader URL for a section/chapter slug like ``16-1-...``."""
        return f"{self.reader_base.rstrip('/')}/{page_slug.lstrip('/')}"


BOOKS: dict[str, BookMeta] = {
    "college-physics-2e": BookMeta(
        slug="college-physics-2e",
        title="OpenStax College Physics 2e",
        license="CC BY 4.0",
        attribution="OpenStax, College Physics 2e",
        reader_base="https://openstax.org/books/college-physics-2e/pages",
    ),
    "calculus-volume-1": BookMeta(
        slug="calculus-volume-1",
        title="OpenStax Calculus Volume 1",
        license="CC BY 4.0",
        attribution="OpenStax, Calculus Volume 1",
        reader_base="https://openstax.org/books/calculus-volume-1/pages",
    ),
    "calculus-volume-2": BookMeta(
        slug="calculus-volume-2",
        title="OpenStax Calculus Volume 2",
        license="CC BY 4.0",
        attribution="OpenStax, Calculus Volume 2",
        reader_base="https://openstax.org/books/calculus-volume-2/pages",
    ),
    "biology-2e": BookMeta(
        slug="biology-2e",
        title="OpenStax Biology 2e",
        license="CC BY 4.0",
        attribution="OpenStax, Biology 2e",
        reader_base="https://openstax.org/books/biology-2e/pages",
    ),
}


@dataclass(frozen=True)
class SectionRef:
    """Parsed mapping.yaml entry — e.g. ``openstax/college-physics-2e/ch-16/16-1``.

    ``book_slug``  → ``college-physics-2e``
    ``chapter``    → ``ch-16``   (always present)
    ``section``    → ``16-1``    (None when the entry is a whole chapter)
    ``url``        → resolved reader URL.
    """

    raw: str
    publisher: str
    book_slug: str
    chapter: str
    section: str | None
    url: str

    @property
    def book(self) -> BookMeta:
        return BOOKS[self.book_slug]


def parse_section_ref(ref: str) -> SectionRef:
    """Turn ``openstax/<book>/<chapter>[/<section>]`` into a SectionRef.

    The reader URL is built by best-effort: OpenStax pages live at
    ``…/pages/<chapter-or-section-anchor>``. The mapping authors hand us
    the anchor; we don't try to fuzzy-match titles. If a section is given,
    that becomes the page slug; otherwise the chapter does.
    """
    parts = ref.strip().split("/")
    if len(parts) < 3 or parts[0].lower() != "openstax":
        raise ValueError(f"unrecognised section ref: {ref!r}")

    publisher = parts[0]
    book_slug = parts[1]
    chapter = parts[2]
    section: str | None = parts[3] if len(parts) >= 4 else None

    if book_slug not in BOOKS:
        raise ValueError(f"unknown book {book_slug!r} in section ref {ref!r}")

    book = BOOKS[book_slug]
    page_slug = section or chapter
    url = book.page_url(page_slug)

    return SectionRef(
        raw=ref,
        publisher=publisher,
        book_slug=book_slug,
        chapter=chapter,
        section=section,
        url=url,
    )


@lru_cache(maxsize=1)
def load_mapping() -> dict[str, list[str]]:
    """Load and validate `mapping.yaml`. Cached for the process lifetime."""
    if not MAPPING_PATH.exists():
        raise FileNotFoundError(f"missing mapping.yaml at {MAPPING_PATH}")
    raw: Any = yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("mapping.yaml root must be a mapping")
    out: dict[str, list[str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"mapping.yaml: non-string key {key!r}")
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"mapping.yaml: {key!r} must map to a list of strings")
        out[key] = list(value)
    return out


def resolve_topic(topic_slug: str) -> list[SectionRef]:
    """Return the SectionRefs configured in mapping.yaml for ``topic_slug``."""
    mapping = load_mapping()
    if topic_slug not in mapping:
        raise KeyError(f"topic slug {topic_slug!r} not in mapping.yaml")
    return [parse_section_ref(r) for r in mapping[topic_slug]]


def parse_topic_slug(topic_slug: str) -> tuple[str, int, str]:
    """Split ``<course>.unit-<N>.<topic>`` into (course, unit_n, topic_tail).

    Raises ValueError on a malformed slug. Used by the CLI to look the topic
    up by (course slug, unit n, topic name) when wiring B2's persister.
    """
    parts = topic_slug.split(".")
    if len(parts) != 3 or not parts[1].startswith("unit-"):
        raise ValueError(
            f"topic slug {topic_slug!r} must be <course>.unit-<N>.<topic>"
        )
    try:
        unit_n = int(parts[1].removeprefix("unit-"))
    except ValueError as e:
        raise ValueError(f"bad unit in topic slug {topic_slug!r}") from e
    return parts[0], unit_n, parts[2]
