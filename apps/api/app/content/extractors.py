"""OpenStax → typed `Section` extraction.

Responsibilities:
  1. Fetch the HTML for an OpenStax section (or read a local fixture when the
     URL begins with ``file://``).
  2. Strip site chrome (nav, footer, sidebar) leaving just the section body.
  3. Normalise MathML to a LaTeX-ish string. We prefer the
     ``<annotation encoding="application/x-tex">`` block embedded by MathJax
     where present; otherwise we fall back to a regex strip of MathML tags
     that keeps the text content.
  4. Surface bolded / italicised tokens as ``named_terms`` — the validator
     in B2 treats them as required-coverage tokens.

This module deliberately uses ``re`` + raw HTML rather than BeautifulSoup: the
extraction surface is small, the OpenStax markup is reasonably consistent, and
keeping the dependency list slim simplifies the deploy.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Section:
    """One extracted OpenStax section (or section bundle).

    ``slug`` is a human-readable id derived from the URL (e.g. ``16-1``).
    ``paragraphs`` are plain-text paragraphs in document order. ``equations``
    and ``named_terms`` are deduped while preserving first-occurrence order so
    the validator's required-coverage list is stable across runs.
    """

    slug: str
    title: str
    paragraphs: list[str] = field(default_factory=list)
    equations: list[str] = field(default_factory=list)
    named_terms: list[str] = field(default_factory=list)
    source_url: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Regex toolkit
# ─────────────────────────────────────────────────────────────────────────────
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_CHROME_TAG_RE = re.compile(
    r"<(nav|header|footer|aside)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_PARA_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)

# MathML — prefer the TeX annotation that OpenStax embeds via MathJax.
_MATH_BLOCK_RE = re.compile(r"<math\b[^>]*>(.*?)</math>", re.IGNORECASE | re.DOTALL)
_TEX_ANNOT_RE = re.compile(
    r'<annotation[^>]*encoding=["\']application/x-tex["\'][^>]*>(.*?)</annotation>',
    re.IGNORECASE | re.DOTALL,
)
# Plain ASCII-style equations in fixture / reader prose: lines that contain
# `=` and at most a few words. We capture anything between ` = ` and the next
# newline / paragraph boundary as a *candidate* — `equations[]` is best-effort
# but always present for the validator to anchor on.
_INLINE_EQ_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_()\\α-ω]{0,20}\s*=\s*[^\n<]{1,80})")

_BOLD_RE = re.compile(
    r"<(b|strong|em|i)\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _strip_tags(html: str) -> str:
    """Crude HTML → text. Collapses entities + whitespace."""
    text = _TAG_RE.sub("", html)
    text = _html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _normalise_math_block(block_html: str) -> str:
    """Pull a readable equation out of a ``<math>...</math>`` block.

    Strategy: if the block has a TeX annotation, use that. Otherwise strip
    the MathML tags and keep the visible characters (operators + identifiers).
    """
    inner = block_html
    tex = _TEX_ANNOT_RE.search(inner)
    if tex:
        return _html.unescape(tex.group(1)).strip()
    return _strip_tags(inner)


def _extract_equations(html: str) -> list[str]:
    """Pull MathML blocks + inline `x = ...` candidates, deduped, in order."""
    seen: set[str] = set()
    out: list[str] = []

    for m in _MATH_BLOCK_RE.finditer(html):
        eq = _normalise_math_block(m.group(1))
        eq = _WS_RE.sub(" ", eq).strip()
        if eq and eq not in seen:
            seen.add(eq)
            out.append(eq)

    # Strip math tags out before scanning for inline equations so we don't
    # double-count.
    stripped = _MATH_BLOCK_RE.sub(" ", html)
    plain = _strip_tags(stripped)
    for m in _INLINE_EQ_RE.finditer(plain):
        eq = m.group(1).strip().rstrip(".,;:")
        eq = _WS_RE.sub(" ", eq)
        if eq and eq not in seen and len(eq) <= 100:
            seen.add(eq)
            out.append(eq)

    return out


def _extract_named_terms(html: str) -> list[str]:
    """Pick out bolded / italicised inline phrases as candidate named terms."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _BOLD_RE.finditer(html):
        term = _strip_tags(m.group(2))
        # Skip URLs, single chars, sentence-length runs.
        if not term or len(term) > 60 or len(term.split()) > 6 or "://" in term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def _extract_paragraphs(html: str) -> list[str]:
    """Pull plain-text paragraphs in document order."""
    paragraphs: list[str] = []
    for m in _PARA_RE.finditer(html):
        text = _strip_tags(m.group(1))
        if text:
            paragraphs.append(text)
    return paragraphs


def _strip_chrome(html: str) -> str:
    """Remove scripts, styles, comments, nav/header/footer/aside blocks."""
    out = _SCRIPT_STYLE_RE.sub(" ", html)
    out = _HTML_COMMENT_RE.sub(" ", out)
    out = _CHROME_TAG_RE.sub(" ", out)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Fixture path — `file://` URLs read from disk so tests don't hit the network.
# ─────────────────────────────────────────────────────────────────────────────
def _parse_fixture_text(slug: str, raw: str, source_url: str) -> Section:
    """Best-effort parse for plain-text OpenStax fixtures.

    The bundled fixture (`openstax-cp2e-ch16.txt`) is ASCII-art-headered prose
    with inline `x = y` equations and ALL-CAPS section banners. We treat
    blank-line-separated blocks as paragraphs and grep equations / bolded
    indicators (`*term*`, **term**, capitalised glossary entries).
    """
    paragraphs: list[str] = []
    title = slug
    title_match = re.search(r"^#\s+(.+?)\s*$", raw, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()

    for block in re.split(r"\n\s*\n", raw):
        block = block.strip()
        if not block:
            continue
        # Skip banners and headings.
        if re.fullmatch(r"=+", block.splitlines()[0]):
            continue
        if block.startswith("#"):
            continue
        # Strip section divider lines like "=== ... ===".
        clean = "\n".join(
            ln for ln in block.splitlines()
            if not re.fullmatch(r"=+", ln.strip())
        ).strip()
        if not clean:
            continue
        paragraphs.append(_WS_RE.sub(" ", clean))

    # Equations: every ` = ` candidate from the prose, plus the standalone
    # equation lines in the fixture which are indented but lack `<p>` tags.
    equations: list[str] = []
    seen_eq: set[str] = set()
    for m in _INLINE_EQ_RE.finditer(raw):
        eq = m.group(1).strip().rstrip(".,;:")
        eq = _WS_RE.sub(" ", eq)
        if eq and eq not in seen_eq and len(eq) <= 100:
            seen_eq.add(eq)
            equations.append(eq)

    # Named terms heuristic: italicised words don't exist in plain text, so we
    # fall back to a small allow-list of capitalised phrases known to recur as
    # OpenStax glossary entries in this corpus.
    named_terms: list[str] = []
    seen_term: set[str] = set()
    for candidate in re.findall(r"\b(?:[A-Z][a-z]+(?:\s+[a-z]+){0,3})\b", raw):
        c = candidate.strip()
        if 4 <= len(c) <= 40 and c.lower() not in seen_term:
            seen_term.add(c.lower())
            named_terms.append(c)
    # The fixture path is for tests and the B0 spike — we don't need a
    # surgical term list, just a non-empty one. Cap at 30.
    named_terms = named_terms[:30]

    return Section(
        slug=slug,
        title=title,
        paragraphs=paragraphs,
        equations=equations,
        named_terms=named_terms,
        source_url=source_url,
    )


def _read_fixture(url: str) -> str:
    """Resolve a ``file://`` URL to disk contents (UTF-8)."""
    parsed = urlparse(url)
    # On Windows a `file:///C:/...` path comes through as
    # `path='/C:/Users/...'` — strip the leading slash if it precedes a drive
    # letter so Path() resolves correctly.
    raw_path = parsed.path
    if re.match(r"^/[A-Za-z]:/", raw_path):
        raw_path = raw_path.lstrip("/")
    p = Path(raw_path)
    return p.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def extract_section(url: str, *, timeout: float = 20.0) -> Section:
    """Fetch + parse one OpenStax section.

    `url` may be:
      • ``https://openstax.org/books/...``  — fetched over HTTPS.
      • ``file://...openstax-cp2e-ch16.txt`` — read from disk (test path).

    For HTTPS pages we accept either OpenStax's reader HTML or the older CNX
    archive (`openstax/api/v0/contents/`). Slug is the last URL segment.
    """
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1] or "section"

    if parsed.scheme == "file":
        raw = _read_fixture(url)
        # Plain-text fixtures (`.txt`) go through the text parser; HTML
        # fixtures fall through to the HTML pipeline below.
        if url.lower().endswith(".txt"):
            return _parse_fixture_text(slug, raw, url)
        html = raw
    else:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "k12-ai-tutor-content/0.1"})
            r.raise_for_status()
            html = r.text

    cleaned = _strip_chrome(html)
    title_m = _TITLE_RE.search(cleaned)
    title = _strip_tags(title_m.group(1)) if title_m else slug

    paragraphs = _extract_paragraphs(cleaned)
    equations = _extract_equations(cleaned)
    named_terms = _extract_named_terms(cleaned)

    return Section(
        slug=slug,
        title=title,
        paragraphs=paragraphs,
        equations=equations,
        named_terms=named_terms,
        source_url=url,
    )
