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

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.content import scene_tagger  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.logging import get_logger  # noqa: E402

log = get_logger(__name__)


def _tag_step(step: dict) -> dict | None:
    """Return a `{type, params}` scene for a step, or None if nothing fits.

    The rule table + param defaults live in ``app.content.scene_tagger`` so
    the live Q&A endpoint can share them.
    """
    title = scene_tagger.headline_from_html(step.get("html", ""))
    text = f"{step.get('tts', '')} {step.get('html', '')}"
    return scene_tagger.tag(text, title)


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
