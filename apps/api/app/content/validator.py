"""Validator for generated `LessonContent` (B2).

Three gates — all must pass before the persister will write.

  1. **Required-terms coverage** — every term + equation must appear across
     the 8 steps. Terms match case-insensitively; equations match with
     whitespace ignored. ≥90% coverage required (allows dropping at most
     one item out of 10+).

  2. **CER triad (Concept / Equation / Rule)** — at least one step states
     the concept (one of the required terms), one states the equation (a
     required equation inside $...$ or $$...$$ delimiters), and one states
     the rule/consequence (pedagogical glue words: "always", "must", "so",
     "because"). The three hits must land on *different* step indices.

  3. **Schema sanity** — exactly 8 items; every `tts` ≤120 chars; every
     `dur` matches mm:ss AND is monotonically non-decreasing; every `html`
     uses only allow-listed tags (`span.hl-*`, `em`, `strong`, `code`)
     with math always inside `$...$` or `$$...$$`; each step besides step
     0 has exactly one `<span class="hl-*">` highlight (step 0 = boilerplate).

A simple regex pass enforces the HTML allow-list — we deliberately don't
pull in ``bleach`` because the surface is small and the dependency is heavy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.content.schema import LessonContent

VALIDATOR_VERSION = "1.0.0"

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_HTML_TAGS = {"span", "em", "strong", "code"}
ALLOWED_HL_CLASSES = {"hl-y", "hl-b", "hl-p", "hl-g"}
COVERAGE_THRESHOLD_PCT = 90

# Pedagogical "rule / why" cues for gate 2.
_RULE_WORDS_RE = re.compile(
    r"\b(always|must|never|so\b|because|therefore|hence|implies|"
    r"means that|since|whenever)\b",
    re.IGNORECASE,
)

# HTML structure regexes.
_TAG_RE = re.compile(r"<\s*([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")
_SPAN_CLASS_RE = re.compile(r'<span\s+class="([^"]+)"')
_HL_SPAN_RE = re.compile(r'<span\s+class="hl-[ybpg]"[^>]*>')
_INLINE_MATH_RE = re.compile(r"\$([^$\n]{1,200})\$")
_DISPLAY_MATH_RE = re.compile(r"\$\$([^$]{1,400})\$\$", re.DOTALL)
_DUR_RE = re.compile(r"^(\d{1,2}):([0-5]\d)$")

# Bare-ASCII math detector — an identifier-ish token followed by `=` and at
# least one more identifier-ish token. We strip `$...$` content first so
# legitimate math doesn't trip this.
_BARE_MATH_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9_()]{0,15}\s*=\s*[^\s<>]{1,40}"
)


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclass
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ValidationReport:
    """Result of validating one ``LessonContent``.

    ``ok`` is True only when zero failures fired. ``failures`` is a flat
    list of human-readable problem strings — the CLI feeds them back into
    the generator on retry. ``coverage_pct`` is the share of required
    terms+equations that landed somewhere across the 8 steps.
    """

    ok: bool
    failures: list[str] = field(default_factory=list)
    coverage_pct: int = 0
    # Bookkeeping for the retry path — which specific tokens were dropped.
    missing_terms: list[str] = field(default_factory=list)
    missing_equations: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _strip_spaces(s: str) -> str:
    return "".join(s.split())


def _strip_math_blocks(html: str) -> str:
    """Remove `$...$` and `$$...$$` math content. Used to detect bare ASCII
    math that escaped the delimiter requirement."""
    no_display = _DISPLAY_MATH_RE.sub(" ", html)
    return _INLINE_MATH_RE.sub(" ", no_display)


def _normalise_equation(eq: str) -> str:
    """Comparison key for required-equation matching.

    Equations from `Section.equations` can carry unicode (π, √, ω) while
    the lesson HTML wraps them in LaTeX (\\pi, \\sqrt{...}, \\omega).
    We strip spaces and lower-case so substring matching is robust to
    incidental whitespace; full unicode↔latex equivalence is out of scope
    (the model only sees the latex spec in the prompt — it should match).

    Also normalises subscript syntax — OpenStax extraction produces bare
    `x0` / `xf` (no underscore) but our LaTeX prompt now mandates `$x_0$`
    / `$x_f$`. We strip underscores from BOTH the source token and the
    haystack at comparison time, plus any surrounding `\\text{...}` so
    `\\,\\text{m}` doesn't mask a unit match. Result: model output with
    proper subscripts still scores as covering the source equation.
    """
    s = _strip_spaces(eq).lower()
    s = s.replace("_", "")
    # Drop LaTeX text-wrapping (e.g. `\text{m}` → `m`).
    s = s.replace("\\text{", "").replace("\\,", "").replace("\\;", "")
    # Drop trailing braces from \\text{X} stripping.
    s = s.replace("}", "")
    return s


def _all_text(content: LessonContent) -> str:
    return " ".join(s.tts + " " + s.html for s in content.items)


def _normalise_haystack(s: str) -> str:
    """Strip spaces + LaTeX subscript / text-wrap noise so equation matches
    survive `$x_0$` vs `x0` and `\\text{m}` vs `m` differences."""
    out = _strip_spaces(s).lower()
    out = out.replace("_", "")
    out = out.replace("\\text{", "").replace("\\,", "").replace("\\;", "")
    out = out.replace("}", "")
    return out


def _all_text_flat(content: LessonContent) -> str:
    return _normalise_haystack(_all_text(content))


# ─────────────────────────────────────────────────────────────────────────────
# Gate 1 — coverage
# ─────────────────────────────────────────────────────────────────────────────
def _gate_coverage(
    content: LessonContent,
    required_terms: list[str],
    required_equations: list[str],
) -> tuple[list[str], list[str], list[str], int]:
    """Return (failures, missing_terms, missing_equations, coverage_pct)."""
    failures: list[str] = []

    text_lower = _all_text(content).lower()
    flat = _all_text_flat(content).lower()

    missing_terms = [t for t in required_terms if t.lower() not in text_lower]
    missing_eqs = [
        e for e in required_equations if _normalise_equation(e) not in flat
    ]

    total = len(required_terms) + len(required_equations)
    hit = total - len(missing_terms) - len(missing_eqs)
    coverage_pct = int(round(100 * hit / total)) if total > 0 else 100

    if coverage_pct < COVERAGE_THRESHOLD_PCT:
        failures.append(
            f"coverage {coverage_pct}% < {COVERAGE_THRESHOLD_PCT}% "
            f"(missing terms={missing_terms}, missing equations={missing_eqs})"
        )
    return failures, missing_terms, missing_eqs, coverage_pct


# ─────────────────────────────────────────────────────────────────────────────
# Gate 2 — CER triad
# ─────────────────────────────────────────────────────────────────────────────
def _gate_cer_triad(
    content: LessonContent,
    required_terms: list[str],
    required_equations: list[str],
) -> list[str]:
    """At least one step concept + one step equation + one step rule, on
    three *different* indices."""
    failures: list[str] = []

    concept_steps: set[int] = set()
    equation_steps: set[int] = set()
    rule_steps: set[int] = set()

    # Concept = any required term appears in this step (case-insensitive).
    norm_terms = [t.lower() for t in required_terms if t]
    # Equation = any required equation appears inside math delimiters.
    norm_eqs = [_normalise_equation(e) for e in required_equations if e]

    for i, step in enumerate(content.items):
        blob = (step.tts + " " + step.html).lower()
        if norm_terms and any(t in blob for t in norm_terms):
            concept_steps.add(i)

        # Pull `$...$` and `$$...$$` content, flatten, search for required eq.
        math_blocks = _INLINE_MATH_RE.findall(step.html) + _DISPLAY_MATH_RE.findall(
            step.html
        )
        if math_blocks and norm_eqs:
            flat_math = _normalise_haystack(" ".join(math_blocks))
            if any(e in flat_math for e in norm_eqs):
                equation_steps.add(i)

        if _RULE_WORDS_RE.search(blob):
            rule_steps.add(i)

    if not concept_steps:
        failures.append("CER: no step names a required concept (term)")
    if norm_eqs and not equation_steps:
        failures.append(
            "CER: no step contains a required equation inside $...$/$$...$$"
        )
    if not rule_steps:
        failures.append(
            "CER: no step uses rule/why glue words "
            "(always/must/so/because/therefore/...)"
        )

    # Distinct-indices check — only when all three sets are non-empty.
    if concept_steps and (not norm_eqs or equation_steps) and rule_steps:
        # Greedy assignment: try to pick three distinct indices.
        for c in concept_steps:
            for e in equation_steps or {c}:
                for r in rule_steps:
                    if len({c, e, r}) == 3 or (not norm_eqs and len({c, r}) == 2):
                        return failures
        failures.append(
            "CER: concept/equation/rule hits did not land on three "
            "different step indices"
        )

    return failures


# ─────────────────────────────────────────────────────────────────────────────
# Gate 3 — schema sanity (length, html allow-list, math delim, dur, tts)
# ─────────────────────────────────────────────────────────────────────────────
def _gate_schema(
    content: LessonContent,
    required_equations: list[str],
) -> list[str]:
    failures: list[str] = []
    items = content.items

    # Length.
    if len(items) != 8:
        failures.append(f"expected 8 steps, got {len(items)}")

    # tts ≤ 120.
    for i, s in enumerate(items):
        if len(s.tts) > 120:
            failures.append(f"step {i}: tts {len(s.tts)} > 120 chars")

    # dur format + monotonic.
    prev_sec = -1
    for i, s in enumerate(items):
        m = _DUR_RE.match(s.dur)
        if not m:
            failures.append(f"step {i}: dur {s.dur!r} not mm:ss")
            continue
        sec = int(m.group(1)) * 60 + int(m.group(2))
        if sec < prev_sec:
            failures.append(
                f"step {i}: dur {s.dur} not monotonic (prev={prev_sec}s)"
            )
        prev_sec = sec

    # html allow-list + highlight count + math delimiter use.
    norm_eqs = [_normalise_equation(e) for e in required_equations if e]
    for i, s in enumerate(items):
        # Tag allow-list.
        tags = {m.group(1).lower() for m in _TAG_RE.finditer(s.html)}
        bad = tags - ALLOWED_HTML_TAGS
        if bad:
            failures.append(f"step {i}: disallowed html tags {sorted(bad)}")

        # span class allow-list (when present).
        for cls_m in _SPAN_CLASS_RE.finditer(s.html):
            classes = set(cls_m.group(1).split())
            if not classes & ALLOWED_HL_CLASSES:
                failures.append(
                    f"step {i}: bad span class {cls_m.group(1)!r}"
                )

        # Highlight count: step 0 = 0 highlights, others = exactly 1.
        n_hl = len(_HL_SPAN_RE.findall(s.html))
        if i == 0:
            if n_hl != 0:
                failures.append(
                    f"step 0 should have 0 highlights, has {n_hl}"
                )
        else:
            if n_hl != 1:
                failures.append(
                    f"step {i}: expected exactly 1 highlight, got {n_hl}"
                )

        # Math-sanity. Strip the `$...$` and `$$...$$` blocks; if the
        # remainder still has a bare `<identifier> = <expr>` we flag it.
        stripped = _strip_math_blocks(s.html)
        # Drop HTML tags so attribute values aren't mistaken for math.
        no_tags = _TAG_RE.sub(" ", stripped)
        no_tags = re.sub(r"</[^>]+>", " ", no_tags)
        if _BARE_MATH_RE.search(no_tags):
            failures.append(
                f"step {i}: bare ASCII math detected outside $...$ delimiters"
            )

        # If a required equation appears in the step at all, it must sit
        # inside math delimiters.
        if norm_eqs:
            flat_html_no_math = _strip_spaces(no_tags).lower()
            for eq in norm_eqs:
                if eq in flat_html_no_math:
                    failures.append(
                        f"step {i}: required equation present but not "
                        f"wrapped in $...$/$$...$$"
                    )
                    break

    return failures


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────
def validate(
    content: LessonContent,
    required_terms: list[str],
    required_equations: list[str],
) -> ValidationReport:
    """Run all three gates against ``content``. Returns a `ValidationReport`."""
    cov_failures, missing_terms, missing_eqs, coverage_pct = _gate_coverage(
        content, required_terms, required_equations
    )
    cer_failures = _gate_cer_triad(content, required_terms, required_equations)
    schema_failures = _gate_schema(content, required_equations)

    failures = [*cov_failures, *cer_failures, *schema_failures]
    return ValidationReport(
        ok=not failures,
        failures=failures,
        coverage_pct=coverage_pct,
        missing_terms=missing_terms,
        missing_equations=missing_eqs,
    )


__all__ = ["validate", "ValidationReport", "VALIDATOR_VERSION"]
