"""Deterministic scene tagger — shared rule table for the live-drawing system.

Maps a piece of lesson text to one of the 12 typed chalkboard scenes by
keyword-matching against an ordered rule table. NO LLM call, so the result
is auditable and reproducible.

Two callers share this module:
  * ``scripts.tag_scenes`` — batch-tags every step of every topic offline.
  * ``api.v1.qa``          — tags a live follow-up question so the answer
                             is drawn with the same scene engine.

Keep the rule table here as the single source of truth.
"""

from __future__ import annotations

import re

# ── Scene rules ──────────────────────────────────────────────────────────────
# Ordered: the first rule whose pattern matches the text wins. Patterns are
# matched case-insensitively against plain prose (HTML tags + LaTeX stripped).
SCENE_RULES: list[tuple[str, str]] = [
    # Most specific physics concepts first — first match wins.
    ("wave", r"wavelength|crest|trough|transverse|\bwave\b|amplitude"),
    ("spring-mass", r"\bspring\b|hooke|oscillat|simple harmonic|restoring force|periodic motion"),
    ("circular-motion", r"centripetal|circular motion|orbit|uniform circular|rotat"),
    ("projectile-arc", r"projectile|trajectory|\blaunch|parabola|thrown|mid.?air"),
    ("inclined-plane", r"incline|\bramp\b|tilted surface"),
    ("collision", r"collision|collide|elastic|inelastic|bounces off|impulse|momentum"),
    ("energy-bar-chart", r"kinetic energy|potential energy|conservation of energy|"
        r"energy bar|\bwork\b|\bjoule|mechanical energy|stored energy"),
    ("free-body-diagram", r"free.?body|net force|newton'?s (first|second|third)|"
        r"forces acting|friction|\bgravity\b|\btension\b|normal force|\bweight\b|\bforce\b"),
    ("motion-graph", r"position.time|velocity.time|graph of|versus time|"
        r"slope of the line|\bvelocity\b|\bacceleration\b"),
    ("vector-arrows", r"\bvector\b|component of|resultant|magnitude and direction"),
    ("fluid-column", r"\bfluid\b|pressure|buoyan|\bdensity\b|archimedes|bernoulli|submerged"),
    ("number-line", r"displacement|\bposition\b|distance traveled|reference frame"),
]

_TAG_RE = re.compile(r"<[^>]+>")
_MATH_RE = re.compile(r"\$+[^$]*\$+")


def plain_text(text: str) -> str:
    """Strip HTML tags + LaTeX so keyword matching sees prose only."""
    no_tags = _TAG_RE.sub(" ", text or "")
    no_math = _MATH_RE.sub(" ", no_tags)
    return no_math.lower()


def headline_from_html(html: str) -> str:
    """Pull the first hl-* highlight phrase as a scene title; fall back to
    the first few plain words."""
    m = re.search(r'<span class="hl-[^"]*">([^<]+)</span>', html or "")
    if m:
        return _MATH_RE.sub("", m.group(1)).strip()[:48]
    plain = _TAG_RE.sub("", html or "").strip()
    return plain.split(".")[0][:48]


def default_params(scene_type: str, title: str = "") -> dict:
    """Minimal, always-valid params for a scene. The scene components ship
    sensible defaults, so we mostly pass a title and let them fill the rest.
    A couple of scenes look bare with zero params — give those a nudge."""
    base: dict = {"title": title} if title else {}

    if scene_type == "number-line":
        # A bare axis is dull — seed two generic positions + a displacement.
        # Labels are PLAIN TEXT: scene SVG <text> can't typeset LaTeX, so
        # we use Unicode subscripts (x₀) and prose ("displacement").
        base.update(
            {
                "unit": "m",
                "min": 0,
                "max": 10,
                "points": [
                    {"value": 2, "label": "x₀", "color": "blue"},
                    {"value": 8, "label": "xₑ", "color": "yellow"},
                ],
                "arrow": {"from": 2, "to": 8, "label": "displacement"},
            }
        )
    elif scene_type == "wave":
        base["label"] = "both"
    elif scene_type == "motion-graph":
        base.update({"xLabel": "time", "yLabel": "position", "curve": "linear"})
    elif scene_type == "vector-arrows":
        base["showComponents"] = True
    return base


def tag(text: str, title: str = "") -> dict | None:
    """Return a ``{type, params}`` scene for a piece of text, or None.

    ``text`` may contain HTML / LaTeX — it is stripped before matching.
    ``title`` is the caption shown above the diagram.
    """
    haystack = plain_text(text)
    for scene_type, pattern in SCENE_RULES:
        if re.search(pattern, haystack):
            return {"type": scene_type, "params": default_params(scene_type, title)}
    return None


__all__ = [
    "SCENE_RULES",
    "plain_text",
    "headline_from_html",
    "default_params",
    "tag",
]
