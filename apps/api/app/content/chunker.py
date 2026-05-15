"""Paragraph-aware chunker for OpenStax sections.

Goal: pack a Section's paragraphs into chunks of ~200–400 token-equivalents,
without:
  - splitting inside a ``<math>...</math>`` block (preserved as a unit by the
    extractor, so the chunker just refuses to split a paragraph that contains
    one);
  - splitting between a defined term and its definition sentence — when a
    paragraph contains an `... is the/is called ...` clause, the following
    sentence is kept with it.

Token estimate is the conventional ~4-chars-per-token rule. Good enough for
guard rails; the embedder doesn't care about exact counts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.content.extractors import Section

TOKEN_RATIO = 4  # ~chars per token, cl100k-ish

# Sentences that introduce a defined term — heuristic.
_DEFINITION_HINT_RE = re.compile(
    r"\b(?:is the|is called|are called|is defined|are defined|"
    r"refers to|we define|known as|called the)\b",
    re.IGNORECASE,
)


@dataclass
class Chunk:
    """One chunk handed to the embedder + persisted to `lesson_embeddings`."""

    ordinal: int
    text: str
    source_url: str
    equations: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)

    @property
    def estimated_tokens(self) -> int:
        return max(1, len(self.text) // TOKEN_RATIO)


def _est_tokens(text: str) -> int:
    return max(1, len(text) // TOKEN_RATIO)


def _has_math_block(text: str) -> bool:
    return "<math" in text.lower()


def _split_sentences(paragraph: str) -> list[str]:
    """Cheap sentence splitter — keeps trailing punctuation."""
    parts = re.split(r"(?<=[\.!?])\s+(?=[A-Z(])", paragraph.strip())
    return [p.strip() for p in parts if p.strip()]


def _is_definition_pair(prev: str, nxt: str) -> bool:
    """Should `prev` and `nxt` (consecutive paragraphs) stay glued together?

    True when the definition cue lives in `prev` (so `nxt` likely carries
    the elaboration sentence).
    """
    return bool(
        _DEFINITION_HINT_RE.search(prev) and not _DEFINITION_HINT_RE.search(nxt)
    )


def chunk_section(
    section: Section,
    *,
    target_tokens: int = 300,
    min_tokens: int = 200,
    max_tokens: int = 400,
) -> list[Chunk]:
    """Pack `section.paragraphs` into 200–400 token chunks.

    Algorithm:
      1. Walk paragraphs in order, accumulating into the current chunk.
      2. Flush when adding the next paragraph would push us past
         `max_tokens`, EXCEPT when:
           • The current paragraph contains a math block — never split there.
           • The previous paragraph contains a definition cue and the current
             one looks like the elaboration — keep them together.
      3. After packing, scan each chunk's text for any equation / named-term
         strings declared on the Section and attach them to the Chunk.
    """
    paragraphs = [p for p in section.paragraphs if p.strip()]
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_tokens = 0
    ordinal = 0

    def _flush() -> None:
        nonlocal buf, buf_tokens, ordinal
        if not buf:
            return
        text = "\n\n".join(buf).strip()
        chunks.append(
            Chunk(
                ordinal=ordinal,
                text=text,
                source_url=section.source_url,
            )
        )
        ordinal += 1
        buf = []
        buf_tokens = 0

    for _idx, para in enumerate(paragraphs):
        para_tokens = _est_tokens(para)

        # A single oversized paragraph (rare) — split by sentence, keeping
        # math-bearing sentences intact.
        if para_tokens > max_tokens and not _has_math_block(para):
            _flush()
            sent_buf: list[str] = []
            sent_tokens = 0
            for sent in _split_sentences(para):
                s_tok = _est_tokens(sent)
                if sent_tokens + s_tok > max_tokens and sent_buf:
                    text = " ".join(sent_buf).strip()
                    chunks.append(
                        Chunk(
                            ordinal=ordinal,
                            text=text,
                            source_url=section.source_url,
                        )
                    )
                    ordinal += 1
                    sent_buf = [sent]
                    sent_tokens = s_tok
                else:
                    sent_buf.append(sent)
                    sent_tokens += s_tok
            if sent_buf:
                text = " ".join(sent_buf).strip()
                chunks.append(
                    Chunk(
                        ordinal=ordinal,
                        text=text,
                        source_url=section.source_url,
                    )
                )
                ordinal += 1
            continue

        # Definition-pair guard: if previous paragraph ended in a definition
        # cue, glue this one on regardless of size budget.
        if buf and _is_definition_pair(buf[-1], para):
            buf.append(para)
            buf_tokens += para_tokens
            # If we're now genuinely huge (>max + 50%), flush anyway.
            if buf_tokens > int(max_tokens * 1.5):
                _flush()
            continue

        # Math-block guard: never split mid-paragraph. If the para itself
        # contains math we always keep it whole.
        if buf_tokens + para_tokens > max_tokens and buf_tokens >= min_tokens:
            _flush()
            buf = [para]
            buf_tokens = para_tokens
        else:
            buf.append(para)
            buf_tokens += para_tokens

        # Target-size flush — once we're at or past target, close the chunk
        # at the next paragraph boundary.
        if buf_tokens >= target_tokens:
            _flush()

    _flush()

    # Merge a too-small trailing chunk into the previous one — keeps every
    # chunk inside the 200–400 window after the loop.
    if len(chunks) >= 2 and chunks[-1].estimated_tokens < min_tokens:
        last = chunks.pop()
        prev = chunks[-1]
        prev.text = (prev.text + "\n\n" + last.text).strip()

    # Attach equations / named_terms that literally appear in each chunk.
    eqs = section.equations
    terms = section.named_terms
    for c in chunks:
        lower = c.text.lower()
        c.equations = [e for e in eqs if e and e.lower() in lower]
        c.terms = [t for t in terms if t and t.lower() in lower]

    return chunks
