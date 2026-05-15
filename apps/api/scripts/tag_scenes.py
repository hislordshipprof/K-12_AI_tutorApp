"""Deterministic scene-tagger (Phase B3).

Assigns an animated chalkboard scene to each lesson step by keyword-matching
the step's text against a rule table — NO LLM call, so the result is
auditable and reproducible. Every scene component renders cleanly with
minimal params, so a tagged step is guaranteed non-broken.

For each topic in Supabase:
  1. Read `topics.content` (the [{tts, html, dur}, ...] step array).
  2. For each step (skipping step 0, the boilerplate intro), pick the
     best-matching scene type or leave it untagged.
  3. Write `scene: {type, params} | null` onto each step and UPDATE the row.

Idempotent — re-running re-tags from scratch. Run:
    python -m scripts.tag_scenes            # all topics
    python -m scripts.tag_scenes --dry-run  # print, don't write
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.logging import get_logger  # noqa: E402

log = get_logger(__name__)


# ── Scene rules ──────────────────────────────────────────────────────────────
# Ordered: the first rule whose pattern matches the step text wins. Patterns
# are matched case-insensitively against `tts + " " + html` (tags stripped).
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


def _plain(text: str) -> str:
    """Strip HTML tags + LaTeX so keyword matching sees prose only."""
    no_tags = _TAG_RE.sub(" ", text or "")
    no_math = _MATH_RE.sub(" ", no_tags)
    return no_math.lower()


def _headline(html: str) -> str:
    """Pull the first hl-* highlight phrase as a scene title; fall back to
    the first few plain words."""
    m = re.search(r'<span class="hl-[^"]*">([^<]+)</span>', html or "")
    if m:
        return _MATH_RE.sub("", m.group(1)).strip()[:48]
    plain = _TAG_RE.sub("", html or "").strip()
    return plain.split(".")[0][:48]


def _default_params(scene_type: str, step: dict) -> dict:
    """Minimal, always-valid params for a scene. The scene components ship
    sensible defaults, so we mostly pass a title and let them fill the rest.
    A couple of scenes look bare with zero params — give those a nudge."""
    title = _headline(step.get("html", ""))
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


def _tag_step(step: dict) -> dict | None:
    """Return a `{type, params}` scene for a step, or None if nothing fits."""
    text = _plain(step.get("tts", "")) + " " + _plain(step.get("html", ""))
    for scene_type, pattern in SCENE_RULES:
        if re.search(pattern, text):
            return {"type": scene_type, "params": _default_params(scene_type, step)}
    return None


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry_run = "--dry-run" in argv

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    # Hydrate .env (the CLI does this; we run outside the FastAPI lifespan).
    try:
        from dotenv import load_dotenv

        env = API_ROOT / ".env"
        if env.exists():
            load_dotenv(env)
    except ImportError:
        pass

    if not settings.supabase_url:
        print("[tag-scenes] Supabase not configured", file=sys.stderr)
        return 3

    from app.core.supabase import get_supabase

    sb = get_supabase()
    if sb is None:
        print("[tag-scenes] Supabase client unavailable", file=sys.stderr)
        return 3

    topics = sb.table("topics").select("id, name, content").execute()
    rows = getattr(topics, "data", None) or []

    total_steps = 0
    tagged_steps = 0
    topics_touched = 0
    per_scene: dict[str, int] = {}

    for row in rows:
        content = row.get("content")
        if not content or not isinstance(content, list):
            continue
        changed = False
        for i, step in enumerate(content):
            if not isinstance(step, dict):
                continue
            total_steps += 1
            # Step 0 is the boilerplate "Preparing your lesson" intro.
            if i == 0:
                step["scene"] = None
                continue
            scene = _tag_step(step)
            step["scene"] = scene
            changed = True
            if scene:
                tagged_steps += 1
                per_scene[scene["type"]] = per_scene.get(scene["type"], 0) + 1
        if changed and not dry_run:
            sb.table("topics").update({"content": content}).eq(
                "id", row["id"]
            ).execute()
            topics_touched += 1
        elif changed:
            topics_touched += 1
        print(
            f"[tag-scenes] {row.get('name')!r}: "
            f"{sum(1 for s in content if isinstance(s, dict) and s.get('scene'))}"
            f"/{len(content)} steps tagged",
            file=sys.stderr,
        )

    print(
        f"[tag-scenes] {'DRY RUN — ' if dry_run else ''}"
        f"{tagged_steps}/{total_steps} steps tagged across {topics_touched} topics",
        file=sys.stderr,
    )
    for scene_type, n in sorted(per_scene.items(), key=lambda kv: -kv[1]):
        print(f"[tag-scenes]   {scene_type}: {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
