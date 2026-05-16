"""B0 — one-day validation experiment for the content pipeline.

Generates ONE 8-step Aria lesson on Oscillations via gemini-pro-latest with
structured output (response_schema), prints the JSON to stdout, and writes it
to ``b0_oscillations_output.json`` next to this file.

Read-only spike: nothing in this module is imported by production code.

Run:
    cd apps/api && .venv/Scripts/python.exe -m app.content.experiments.b0_oscillations
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Re-use the canonical Aria persona so the experiment matches the agent layer.
from app.agents.prompts import ARIA_BASE_PERSONA

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
API_ROOT = HERE.parents[2]  # apps/api/
FIXTURE_PATH = API_ROOT / "app" / "content" / "fixtures" / "openstax-cp2e-ch16.txt"
OUTPUT_PATH = HERE / "b0_oscillations_output.json"
DOTENV_PATH = API_ROOT / ".env"


# ─────────────────────────────────────────────────────────────────────────────
# Schema (mirrors docs/content-pipeline.md § Generate)
# ─────────────────────────────────────────────────────────────────────────────
class LessonStep(BaseModel):
    tts: str = Field(
        ...,
        description=(
            "Spoken line for Aria's TTS — plain prose, max 120 characters, "
            "no HTML, no LaTeX. Two short sentences max."
        ),
    )
    html: str = Field(
        ...,
        description=(
            "On-screen HTML for the teleprompter. MUST contain exactly one "
            "<span class=\"hl-y|hl-b|hl-p|hl-g\">…</span> highlight. "
            "Allowed tags only: span.hl-*, em, strong, code."
        ),
    )
    dur: str = Field(
        ...,
        description="mm:ss timestamp when this step appears. Monotonically increases.",
    )


class LessonContent(BaseModel):
    items: list[LessonStep]


# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    f"{ARIA_BASE_PERSONA}\n\n"
    "You are writing 8-step lesson content for the in-app teleprompter, "
    "NOT a chat reply. Each step is what Aria says + what the student sees, "
    "for ONE moment of the lesson. Stay in Aria's voice the whole way."
)


RUBRIC = """\
8-STEP RUBRIC — produce exactly 8 items in this order:

  Step 0 — Boilerplate. Use EXACTLY:
           tts: "Preparing your lesson."
           html: "Preparing your lesson…"
           dur: "00:00"

  Steps 1–2 — GROUND the everyday phenomenon. Hook the student in plain
              language using a concrete object (guitar string, swing, spring).
              No equations yet. No jargon.

  Steps 3–5 — NAME the concept and UNFOLD the equation. Introduce amplitude,
              period, frequency, equilibrium, restoring force — one per step
              where possible. Build toward the math gradually.

  Steps 6–7 — STATE the rule and the WHY. End on the canonical relationships:
              T = 1/f, T = 2π√(m/k), x(t) = A cos(ωt). The LAST step should
              contain the canonical equation literally inside the highlight.

HARD CONSTRAINTS — every step (except step 0's boilerplate) must obey:

  • tts ≤ 120 characters, max 2 sentences, no HTML, no LaTeX.
  • html contains EXACTLY ONE <span class="hl-y">, <span class="hl-b">,
    <span class="hl-p">, or <span class="hl-g"> highlight wrapping the key
    phrase. Cycle the colors so consecutive steps differ.
  • Allowed html tags: <span class="hl-*">, <em>, <strong>, <code>.
    NO other tags. NO MathML. NO inline styles.
  • dur is mm:ss and strictly increases. Whole lesson ≈ 13 minutes.
  • Voice: warm, plain, like a patient older sibling. Never lecture.
  • Do NOT use phrases like "as we saw earlier" or "remember when" — this
    is step-by-step, the student has not seen previous content yet.

REQUIRED COVERAGE — across the 8 steps, all of these must appear at least once:

  Terms (case-insensitive): amplitude, period, frequency, equilibrium,
                            restoring force.
  Equations (literal — match string exactly, spaces ignored):
            T = 1/f
            T = 2π√(m/k)
            x(t) = A cos(ωt)
"""


def build_user_prompt(source_text: str) -> str:
    return (
        "TOPIC: Oscillations: Amplitude, Period & Frequency\n"
        "AP Course: AP Physics 1 — Unit 7 (CED 2024)\n"
        "Audience: high-school students aged 15–18.\n\n"
        f"{RUBRIC}\n\n"
        "SOURCE PASSAGES (OpenStax College Physics 2e, §16.1–16.3, CC BY 4.0). "
        "Anchor the lesson here — do not introduce facts not present below.\n"
        "----- BEGIN SOURCE -----\n"
        f"{source_text}\n"
        "----- END SOURCE -----\n\n"
        "Now produce the 8-step lesson as structured JSON matching the schema."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Validator (rubric gate — independent of the model)
# ─────────────────────────────────────────────────────────────────────────────
REQUIRED_TERMS = ["amplitude", "period", "frequency", "equilibrium", "restoring force"]
REQUIRED_EQUATIONS = ["T = 1/f", "T = 2π√(m/k)", "x(t) = A cos(ωt)"]
ALLOWED_HTML_TAGS = {"span", "em", "strong", "code"}
ALLOWED_HL_CLASSES = {"hl-y", "hl-b", "hl-p", "hl-g"}


def _strip_spaces(s: str) -> str:
    return "".join(s.split())


def validate(lesson: LessonContent) -> dict[str, Any]:
    import re

    items = lesson.items
    report: dict[str, Any] = {"checks": {}, "issues": []}

    # 1. Length
    ok_len = len(items) == 8
    report["checks"]["length_eq_8"] = ok_len
    if not ok_len:
        report["issues"].append(f"expected 8 steps, got {len(items)}")

    all_text = " ".join(s.tts + " " + s.html for s in items).lower()

    # 2. Required terms
    missing_terms = [t for t in REQUIRED_TERMS if t.lower() not in all_text]
    report["checks"]["all_terms_present"] = not missing_terms
    if missing_terms:
        report["issues"].append(f"missing terms: {missing_terms}")

    # 3. Required equations (space-insensitive literal match)
    flat = _strip_spaces(" ".join(s.tts + " " + s.html for s in items))
    missing_eqs = [e for e in REQUIRED_EQUATIONS if _strip_spaces(e) not in flat]
    report["checks"]["all_equations_present"] = not missing_eqs
    if missing_eqs:
        report["issues"].append(f"missing equations: {missing_eqs}")

    # 4. TTS length
    long_tts = [(i, len(s.tts)) for i, s in enumerate(items) if len(s.tts) > 120]
    report["checks"]["tts_le_120"] = not long_tts
    if long_tts:
        report["issues"].append(f"tts >120 chars at indices: {long_tts}")

    # 5. HTML allow-list — quick regex pass for disallowed tags
    tag_re = re.compile(r"<\s*([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")
    span_class_re = re.compile(r'<span\s+class="([^"]+)"')
    hl_count_re = re.compile(r'<span\s+class="hl-[ybpg]"')
    bad_html: list[str] = []
    bad_highlights: list[str] = []
    for i, s in enumerate(items):
        tags = {m.group(1).lower() for m in tag_re.finditer(s.html)}
        bad = tags - ALLOWED_HTML_TAGS
        if bad:
            bad_html.append(f"step {i}: disallowed tags {bad}")
        for cls_m in span_class_re.finditer(s.html):
            classes = set(cls_m.group(1).split())
            if not classes & ALLOWED_HL_CLASSES and "hl-" in cls_m.group(1):
                bad_html.append(f"step {i}: bad span class {cls_m.group(1)!r}")
        # Step 0 is boilerplate — allow zero highlights there.
        n_hl = len(hl_count_re.findall(s.html))
        if i == 0:
            if n_hl != 0:
                bad_highlights.append(f"step 0 should have 0 highlights, has {n_hl}")
        else:
            if n_hl != 1:
                bad_highlights.append(f"step {i} should have exactly 1 highlight, has {n_hl}")
    report["checks"]["html_allowlist"] = not bad_html
    report["checks"]["exactly_one_highlight"] = not bad_highlights
    if bad_html:
        report["issues"].extend(bad_html)
    if bad_highlights:
        report["issues"].extend(bad_highlights)

    # 6. dur monotonic mm:ss
    dur_re = re.compile(r"^([0-9]{1,2}):([0-5][0-9])$")
    prev_sec = -1
    dur_ok = True
    for i, s in enumerate(items):
        m = dur_re.match(s.dur)
        if not m:
            dur_ok = False
            report["issues"].append(f"step {i}: dur {s.dur!r} not mm:ss")
            continue
        sec = int(m.group(1)) * 60 + int(m.group(2))
        if sec < prev_sec:
            dur_ok = False
            report["issues"].append(f"step {i}: dur {s.dur} not monotonic (prev={prev_sec}s)")
        prev_sec = sec
    report["checks"]["dur_monotonic_mmss"] = dur_ok

    report["all_pass"] = all(report["checks"].values())
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    # Make stdout UTF-8 so unicode math symbols (π √ ω) print on Windows.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    load_dotenv(DOTENV_PATH)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY missing from apps/api/.env", file=sys.stderr)
        return 2

    source_text = FIXTURE_PATH.read_text(encoding="utf-8")
    user_prompt = build_user_prompt(source_text)

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)

    # Pinned fallback — never a moving *-latest alias on a provenance path (M.3).
    model_name = os.environ.get("GEMINI_MODEL_PRO", "gemini-3.1-pro-preview")

    config = genai_types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=LessonContent,
        temperature=0.6,
    )

    print(f"-> calling {model_name} with response_schema=LessonContent ...", file=sys.stderr)
    response = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=config,
    )

    # The new SDK exposes the parsed Pydantic object on `.parsed` when
    # response_schema is set; fall back to JSON-parsing `.text` otherwise.
    parsed: LessonContent | None = getattr(response, "parsed", None)
    if parsed is None:
        raw = getattr(response, "text", "") or ""
        if not raw:
            print("ERROR: empty response from Gemini", file=sys.stderr)
            return 3
        parsed = LessonContent.model_validate_json(raw)

    out_dict = parsed.model_dump()
    print(json.dumps(out_dict, indent=2, ensure_ascii=False))

    OUTPUT_PATH.write_text(
        json.dumps(out_dict, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\n-> wrote {OUTPUT_PATH}", file=sys.stderr)

    report = validate(parsed)
    print("\n=== VALIDATION ===", file=sys.stderr)
    for k, v in report["checks"].items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}", file=sys.stderr)
    if report["issues"]:
        print("  issues:", file=sys.stderr)
        for i in report["issues"]:
            print(f"    - {i}", file=sys.stderr)
    print(f"  overall: {'PASS' if report['all_pass'] else 'FAIL'}", file=sys.stderr)

    # Persist the validation report next to the JSON for the write-up.
    (HERE / "b0_oscillations_validation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
