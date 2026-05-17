"""Course cover-art generation (task 5.2).

`model-strategy.md` §4: a teacher course gets a generated cover image once,
at publish time, cached. `generate_course_cover` runs as a fire-and-forget
background task off the topic-publish endpoint — it is **best-effort** (a
failure leaves `courses.cover_image_path` NULL and the dashboard falls back
to the gradient) and **one-shot** (a course that already has a cover is left
untouched, so re-publishing topics never regenerates it).
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.core.supabase import get_supabase
from app.services.gemini import GeminiService

log = get_logger(__name__)

COVER_BUCKET = "course-covers"


def _cover_prompt(title: str, subject: str | None) -> str:
    """Build the Nano Banana 2 prompt — a flat subject illustration, no text."""
    return (
        "A clean, modern flat-style vector illustration for an educational "
        f'course cover. The course is "{title}"'
        + (f", a {subject} course" if subject else "")
        + ". Show a single clear focal subject that evokes the topic, using "
        "a bright friendly colour palette, simple geometric shapes and a "
        "soft background. Wide 16:9 banner composition, centred. Absolutely "
        "no text, no letters, no words and no numbers anywhere in the image."
    )


async def generate_course_cover(course_id: str) -> None:
    """Generate + store a cover for a course. Best-effort, one-shot.

    No-ops when Supabase is unavailable, the course is missing, or the
    course already has a `cover_image_path`. Never raises.
    """
    supabase = get_supabase()
    if supabase is None:
        return
    try:
        resp = (
            supabase.table("courses")
            .select("id,title,subject,cover_image_path")
            .eq("id", course_id)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if not rows:
            return
        course = rows[0]
        if course.get("cover_image_path"):
            return  # already has a cover — one-shot, never regenerate.

        prompt = _cover_prompt(
            str(course.get("title") or "Course"), course.get("subject")
        )
        image = await GeminiService().generate_image(prompt)

        key = f"{course_id}.png"
        supabase.storage.from_(COVER_BUCKET).upload(
            key,
            image,
            {"content-type": "image/png", "upsert": "true"},
        )
        supabase.table("courses").update({"cover_image_path": key}).eq(
            "id", course_id
        ).execute()
        log.info("course_cover_generated", course_id=course_id, bytes=len(image))
    except Exception as e:  # noqa: BLE001
        log.warning("course_cover_failed", course_id=course_id, error=str(e))
