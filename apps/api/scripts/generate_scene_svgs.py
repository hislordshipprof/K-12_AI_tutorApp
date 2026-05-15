"""Model-authored fallback drawings (Phase C — experimental).

The deterministic tagger (`tag_scenes.py`) covers steps that fit one of the
12 typed physics scenes. Everything else — biology, chemistry, the prose-only
steps of a physics lesson — falls back to the text chalkboard.

This script fills that gap: for each *untagged* step it asks Gemini to draw a
simple chalk diagram as a STRUCTURED list of primitives (line / circle / rect
/ path / text / …) — never as an SVG string. The primitives are validated
here against a strict whitelist, then written as
`scene: {type: "custom-svg", params: {title, elements}}`. The
`CustomSvgScene` React component renders each primitive as a real SVG element,
so nothing the model emits can inject markup.

Experimental: model output quality varies. Run small, review, then scale up.

    python -m scripts.generate_scene_svgs --dry-run --limit 5      # preview
    python -m scripts.generate_scene_svgs --limit 5                # write 5
    python -m scripts.generate_scene_svgs --topic <uuid>           # one topic
    python -m scripts.generate_scene_svgs                          # all untagged

Idempotent: only steps whose `scene` is null/missing are touched, so a
re-run picks up where it left off. Pass --force to also redraw existing
custom-svg steps.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.logging import get_logger  # noqa: E402

log = get_logger(__name__)

# ── Primitive schema (the model's structured-output contract) ────────────────
# A flat element list — the React renderer whitelists every field again, so
# this schema is the *first* of two validation gates, not the only one.

_PALETTE = {"white", "blue", "yellow", "pink", "green"}
_ANCHORS = {"start", "middle", "end"}
_ELEMENTS = {
    "line",
    "arrow",
    "polyline",
    "path",
    "rect",
    "circle",
    "ellipse",
    "polygon",
    "text",
}


class Primitive(BaseModel):
    """One drawing element. Only the fields relevant to `el` are read."""

    el: str = Field(
        description="One of: line arrow polyline path rect circle ellipse polygon text"
    )
    # geometry — all optional; the renderer defaults missing ones to 0.
    # arrow uses x1,y1 (tail) → x2,y2 (head); arrowhead is drawn for you.
    x: float | None = None
    y: float | None = None
    x1: float | None = None
    y1: float | None = None
    x2: float | None = None
    y2: float | None = None
    cx: float | None = None
    cy: float | None = None
    r: float | None = None
    rx: float | None = None
    ry: float | None = None
    width: float | None = None
    height: float | None = None
    d: str | None = Field(default=None, description="path data, only for el=path")
    points: str | None = Field(
        default=None, description="'x,y x,y …' for polyline/polygon"
    )
    # presentation
    stroke: str | None = Field(default=None, description="palette: white blue yellow pink green")
    fill: str | None = Field(default=None, description="palette key, or 'none'")
    strokeWidth: float | None = None
    dash: bool | None = None
    opacity: float | None = Field(
        default=None, description="0-1; use <1 for faint guide shapes"
    )
    text: str | None = Field(default=None, description="caption, only for el=text")
    fontSize: float | None = None
    textAnchor: str | None = Field(
        default=None, description="text only: start | middle | end"
    )
    group: int | None = Field(
        default=None,
        description="elements with the same group index reveal together",
    )


class SceneDrawing(BaseModel):
    """The model's whole answer for one step."""

    title: str = Field(description="≤ 6-word caption for the drawing")
    elements: list[Primitive] = Field(
        description="6-22 primitives, back-to-front draw order"
    )


_SYSTEM_PROMPT = """You are a chalkboard illustrator for a K-12 tutor. \
Given a lesson step, draw ONE simple, schematic chalk diagram that helps a \
student picture the concept.

CANVAS: a 900 wide x 530 tall viewBox. The `title` field you return is \
drawn for you near the top — do NOT add a text element that repeats it. \
Keep your elements within x: 60-840, y: 190-500.

OUTPUT: a flat list of 6-22 drawing primitives, in back-to-front order \
(background shapes first, labels last). Each primitive is one of: line, \
arrow, polyline, path, rect, circle, ellipse, polygon, text.

RULES:
- Schematic, not detailed. Think a teacher's quick board sketch: a few shapes \
and 2-5 short text labels. Never more than 22 elements.
- Colours are palette keys ONLY: white, blue, yellow, pink, green. Use white \
for structure, colours for emphasis. Default stroke is white.
- For an outline shape set fill to "none" (it then "draws on"); set a palette \
fill only for a solid shape.
- Use an `arrow` (x1,y1 tail -> x2,y2 head) for forces, motion, flow, and for \
pointing a label at the part it names — the arrowhead is drawn for you, so \
never build one by hand from a polygon.
- Set `opacity` below 1 (e.g. 0.35) on faint guide lines or background shapes \
so the key parts of the drawing stand out.
- text elements: short labels (1-3 words). EVERY text element MUST include \
both `x` and `y` — a label with no coordinates is dropped. Put the label \
NEXT TO what it names and set `textAnchor` so it sits cleanly — `end` for a \
label to the LEFT of its target, `start` for a label to the RIGHT, `middle` \
above/below. No LaTeX, no math symbols that need typesetting — plain words \
and simple units only.
- Give a shape and its label the SAME `group` number so they reveal \
together; leave `group` off to reveal an element on its own.
- Use coordinates that actually fit the canvas. Center the drawing.
- Do NOT restate the lesson text. Draw the concept.

Return only the structured object."""


def _user_prompt(topic: str, step_text: str) -> str:
    return (
        f"Topic: {topic}\n\n"
        f"Lesson step the student is hearing right now:\n{step_text}\n\n"
        "Draw the chalkboard diagram for this step."
    )


_TAG_RE = re.compile(r"<[^>]+>")
_MATH_RE = re.compile(r"\$+[^$]*\$+")


def _plain(text: str) -> str:
    no_tags = _TAG_RE.sub(" ", text or "")
    no_math = _MATH_RE.sub(" ", no_tags)
    return re.sub(r"\s+", " ", no_math).strip()


# ── Validation gate — drop anything the renderer would reject anyway ─────────


def _clean_element(p: Primitive) -> dict | None:
    """Coerce one Primitive into a minimal, renderer-safe dict, or None."""
    if p.el not in _ELEMENTS:
        return None
    out: dict[str, Any] = {"el": p.el}

    def put_num(key: str, val: float | None) -> None:
        if isinstance(val, (int, float)) and -2000 <= val <= 4000:
            out[key] = float(val)

    for key in ("x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
                "width", "height", "strokeWidth", "fontSize"):
        put_num(key, getattr(p, key))

    if p.el == "path" and isinstance(p.d, str):
        # path data is geometry only — keep ascii path grammar, cap length
        if re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9eE,.\s+-]+", p.d or ""):
            out["d"] = p.d[:2000]
    if p.el in ("polyline", "polygon") and isinstance(p.points, str):
        if re.fullmatch(r"[0-9eE,.\s+-]+", p.points or ""):
            out["points"] = p.points[:2000]
    if p.el == "text" and isinstance(p.text, str):
        out["text"] = p.text[:120]

    if isinstance(p.stroke, str) and p.stroke in _PALETTE:
        out["stroke"] = p.stroke
    if isinstance(p.fill, str) and (p.fill in _PALETTE or p.fill == "none"):
        out["fill"] = p.fill
    if p.dash is True:
        out["dash"] = True
    if isinstance(p.opacity, (int, float)) and 0 <= p.opacity <= 1:
        out["opacity"] = float(p.opacity)
    if p.el == "text" and isinstance(p.textAnchor, str) and p.textAnchor in _ANCHORS:
        out["textAnchor"] = p.textAnchor
    if isinstance(p.group, int) and not isinstance(p.group, bool) and 0 <= p.group <= 40:
        out["group"] = p.group

    # An element with no usable geometry is dead weight. A text label needs
    # both coords or it piles up unplaceable at the canvas origin.
    geom_keys = {"x", "y", "x1", "x2", "cx", "d", "points"}
    if p.el == "text":
        if not out.get("text") or "x" not in out or "y" not in out:
            return None
    elif not (geom_keys & out.keys()):
        return None
    return out


def _validate(drawing: SceneDrawing) -> dict | None:
    """Turn a model SceneDrawing into clean `params`, or None if too sparse."""
    elements = [c for p in drawing.elements if (c := _clean_element(p))]
    if len(elements) < 3:
        return None
    return {
        "title": (drawing.title or "").strip()[:80],
        "elements": elements[:40],
    }


# ── Model call ───────────────────────────────────────────────────────────────


async def _draw_step(gemini: Any, model: str, topic: str, step_text: str) -> dict | None:
    from tenacity import (
        AsyncRetrying,
        retry_if_exception,
        stop_after_attempt,
        wait_exponential,
    )

    retryable = ("rate limit", "429", "500", "502", "503", "504",
                 "deadline exceeded", "unavailable", "internal error")

    def is_retryable(exc: BaseException) -> bool:
        return any(p in str(exc).lower() for p in retryable)

    config: dict[str, Any] = {
        "system_instruction": _SYSTEM_PROMPT,
        "response_mime_type": "application/json",
        "response_schema": SceneDrawing,
        "temperature": 0.7,
    }
    client = gemini.client
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(is_retryable),
        reraise=True,
    ):
        with attempt:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=_user_prompt(topic, step_text),
                config=config,
            )
            drawing: SceneDrawing | None = getattr(resp, "parsed", None)
            if drawing is None:
                raw = getattr(resp, "text", "") or ""
                if not raw:
                    raise RuntimeError("generate_scene_svgs: empty model response")
                drawing = SceneDrawing.model_validate_json(raw)
            return _validate(drawing)
    return None


# ── Driver ───────────────────────────────────────────────────────────────────


async def _run(args: argparse.Namespace) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    try:
        from dotenv import load_dotenv

        env = API_ROOT / ".env"
        if env.exists():
            load_dotenv(env)
    except ImportError:
        pass

    if not settings.supabase_url:
        print("[scene-svg] Supabase not configured", file=sys.stderr)
        return 3

    from app.core.supabase import get_supabase
    from app.services.gemini import GeminiService

    sb = get_supabase()
    if sb is None:
        print("[scene-svg] Supabase client unavailable", file=sys.stderr)
        return 3

    query = sb.table("topics").select("id, name, content")
    if args.topic:
        query = query.eq("id", args.topic)
    topics = query.execute()
    rows = getattr(topics, "data", None) or []

    gemini = GeminiService()
    model = settings.gemini_model_pro

    processed = 0
    drawn = 0
    skipped_sparse = 0
    limit = args.limit or 0  # 0 → unlimited

    for row in rows:
        content = row.get("content")
        if not content or not isinstance(content, list):
            continue
        topic_name = row.get("name") or "Lesson"
        changed = False

        for i, step in enumerate(content):
            if not isinstance(step, dict) or i == 0:
                continue
            existing = step.get("scene")
            # Untagged → eligible. Existing custom-svg → eligible only with --force.
            if existing:
                if not (args.force and isinstance(existing, dict)
                        and existing.get("type") == "custom-svg"):
                    continue
            if limit and processed >= limit:
                break

            step_text = _plain(step.get("tts", "")) + " " + _plain(
                step.get("html", "")
            )
            step_text = step_text.strip()[:1200]
            if len(step_text) < 20:
                continue

            processed += 1
            try:
                # Hard ceiling so one stuck model call can't hang the run.
                params = await asyncio.wait_for(
                    _draw_step(gemini, model, topic_name, step_text),
                    timeout=90,
                )
            except (asyncio.TimeoutError, TimeoutError):
                print(
                    f"[scene-svg] {topic_name!r} step {i}: timed out, skipped",
                    file=sys.stderr,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[scene-svg] {topic_name!r} step {i}: model error — {exc}",
                    file=sys.stderr,
                )
                continue

            if params is None:
                skipped_sparse += 1
                print(
                    f"[scene-svg] {topic_name!r} step {i}: too sparse, skipped",
                    file=sys.stderr,
                )
                continue

            drawn += 1
            print(
                f"[scene-svg] {topic_name!r} step {i}: "
                f"{len(params['elements'])} elements — {params['title']!r}",
                file=sys.stderr,
            )
            if args.dry_run:
                print(f"           {params}", file=sys.stderr)
            else:
                step["scene"] = {"type": "custom-svg", "params": params}
                changed = True

        if changed and not args.dry_run:
            sb.table("topics").update({"content": content}).eq(
                "id", row["id"]
            ).execute()

        if limit and processed >= limit:
            break

    print(
        f"[scene-svg] {'DRY RUN — ' if args.dry_run else ''}"
        f"{drawn} drawings written, {skipped_sparse} skipped (sparse), "
        f"{processed} steps processed",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate_scene_svgs")
    parser.add_argument("--dry-run", action="store_true",
                        help="print drawings, write nothing")
    parser.add_argument("--limit", type=int, default=0,
                        help="max steps to process (0 = all untagged)")
    parser.add_argument("--topic", type=str, default=None,
                        help="restrict to one topic id")
    parser.add_argument("--force", action="store_true",
                        help="also redraw existing custom-svg steps")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
