"""Prompt builders for the content pipeline (B2 + B3).

Two distinct surfaces share this module:

  • **Generation** (B2 — offline) — ``LESSON_GENERATION_SYSTEM_PROMPT`` and
    ``LESSON_GENERATION_USER_PROMPT`` drive ``generator.LessonGenerator``.
    The system slot pins Aria's persona; the user slot supplies topic +
    required tokens + the 8-step rubric + retrieved source chunks.

  • **Runtime RAG** (B3 — request-time) — ``RAG_QUESTION_PROMPT`` grounds
    Aria's Socratic reply in the chunks the retriever surfaces. It is
    defined here so B3 can drop it into the agents layer without growing
    a parallel prompt module. **Not** wired into the live tutor yet.

Persona constants (``ARIA_BASE_PERSONA`` + rule 8 from ``SOCRATIC_RULES``)
are re-used verbatim from ``app.agents.prompts`` so generation and live
chat share one voice.
"""

from __future__ import annotations

from app.agents.prompts import ARIA_BASE_PERSONA, SOCRATIC_RULES
from app.agents.state import SessionState
from app.content.chunker import Chunk

# ─────────────────────────────────────────────────────────────────────────────
# Generation — system slot
# ─────────────────────────────────────────────────────────────────────────────
# Aria's persona + a hard reminder that this is teleprompter content, not a
# chat reply. Rule 8 (the LaTeX math-formatting rule) is the one rule from
# SOCRATIC_RULES that *does* apply to lesson HTML — we surface it explicitly
# so the model doesn't fall back to bare-ASCII equations like "T = 1/f".
LESSON_GENERATION_SYSTEM_PROMPT = (
    f"{ARIA_BASE_PERSONA}\n\n"
    "You are writing 8-step lesson content for the in-app teleprompter, "
    "NOT a chat reply. Each step is what Aria says + what the student sees, "
    "for ONE moment of the lesson. Stay in Aria's voice the whole way.\n\n"
    "MATH FORMATTING — every equation, variable, or numeric expression in "
    "the `html` field MUST be wrapped in LaTeX delimiters so the frontend "
    "KaTeX renderer can typeset it. Use $...$ for inline math and $$...$$ "
    "for display math. Examples:\n"
    "   • inline: 'the period is $T = 1/f$'\n"
    "   • display: '$$T = 2\\pi \\sqrt{m/k}$$'\n"
    "   • single variables: $v$, $\\lambda$, $\\omega$\n"
    "Do NOT emit bare ASCII math like 'T = 1/f' outside delimiters. Do NOT "
    "use loose Unicode math symbols (no bare 'π', '√', '²'); use LaTeX "
    "commands inside delimiters ($\\pi$, $\\sqrt{}$, $^2$)."
)


# ─────────────────────────────────────────────────────────────────────────────
# Generation — user slot
# ─────────────────────────────────────────────────────────────────────────────
_BASE_RUBRIC = """\
8-STEP RUBRIC — produce exactly 8 items in this order:

  Step 0 — Boilerplate. Use EXACTLY:
           tts: "Preparing your lesson."
           html: "Preparing your lesson…"
           dur: "00:00"

  Steps 1–2 — GROUND the everyday phenomenon. Hook the student in plain
              language using a concrete object. No equations yet, no jargon.

  Steps 3–5 — NAME the concept and UNFOLD the equation. Introduce the
              required terms — one per step where possible. Build toward
              the math gradually.

  Steps 6–7 — STATE the rule and the WHY. End on the canonical equation(s).
              The LAST step MUST contain a canonical equation literally
              inside its highlight, wrapped in $...$ delimiters.

HARD CONSTRAINTS — every step (except step 0's boilerplate) MUST obey:

  • tts ≤ 120 characters, max 2 sentences, plain prose, no HTML, no LaTeX.
  • html contains EXACTLY ONE <span class="hl-y">, <span class="hl-b">,
    <span class="hl-p">, or <span class="hl-g"> highlight wrapping the key
    phrase. Cycle the colors so consecutive steps differ.
  • Allowed html tags: <span class="hl-*">, <em>, <strong>, <code>.
    NO other tags. NO MathML. NO inline styles. NO <p>, NO <br>.
  • All math (equations AND single variables) MUST be inside $...$ or
    $$...$$ LaTeX delimiters. Bare ASCII like "T = 1/f" is forbidden.
  • dur is mm:ss and strictly increases. Whole lesson ≈ 13 minutes.
  • Voice: warm, plain, like a patient older sibling. Never lecture.
  • Do NOT use "as we saw earlier", "remember when", "before we" — this is
    step-by-step and the student has not seen previous content yet.
"""


def _format_required_terms(terms: list[str]) -> str:
    if not terms:
        return "  (no required terms — use natural vocabulary)"
    return "\n".join(f"  • {t}" for t in terms)


def _format_required_equations(equations: list[str]) -> str:
    if not equations:
        return "  (no required equations — focus on the qualitative idea)"
    return "\n".join(f"  • {e}" for e in equations)


def _format_source_chunks(chunks: list[Chunk]) -> str:
    """Render retrieved chunks as a labelled, model-readable block."""
    if not chunks:
        return "(no source chunks — fall back to general curriculum knowledge)"
    parts: list[str] = []
    for i, c in enumerate(chunks, 1):
        # Trim individual chunks to keep the prompt budget sane.
        body = c.text.strip()
        if len(body) > 1400:
            body = body[:1400].rstrip() + "…"
        parts.append(f"[chunk {i} | ordinal={c.ordinal}]\n{body}")
    return "\n\n".join(parts)


def LESSON_GENERATION_USER_PROMPT(
    topic_name: str,
    required_terms: list[str],
    required_equations: list[str],
    source_chunks: list[Chunk],
    *,
    extra_instructions: str | None = None,
) -> str:
    """Build the user-slot prompt for an 8-step lesson generation call.

    ``extra_instructions`` is appended at the bottom — the validator-retry
    path uses this slot to inject failure context (e.g. "you dropped
    `T = 2π√(m/k)` — include it literally in step 6 or 7").
    """
    body = (
        f"TOPIC: {topic_name}\n"
        "Audience: high-school students aged 15–18.\n\n"
        f"{_BASE_RUBRIC}\n"
        "REQUIRED COVERAGE — across the 8 steps, all of these must appear "
        "at least once (≥90% coverage required across terms+equations).\n\n"
        "Required terms (case-insensitive substring match):\n"
        f"{_format_required_terms(required_terms)}\n\n"
        "Required equations (match the LaTeX literally inside $...$ or "
        "$$...$$; spaces are ignored):\n"
        f"{_format_required_equations(required_equations)}\n\n"
        "SOURCE PASSAGES (anchor the lesson here — do not introduce facts "
        "not supported by these passages):\n"
        "----- BEGIN SOURCE -----\n"
        f"{_format_source_chunks(source_chunks)}\n"
        "----- END SOURCE -----\n\n"
        "Produce the 8-step lesson as structured JSON matching the schema. "
        "Every required term and every required equation must appear "
        "literally somewhere across the steps."
    )
    if extra_instructions:
        body += (
            "\n\nADDITIONAL INSTRUCTIONS (validator retry — read carefully):\n"
            f"{extra_instructions}"
        )
    return body


# ─────────────────────────────────────────────────────────────────────────────
# Runtime RAG (B3 will wire this into agents/tutor.py)
# ─────────────────────────────────────────────────────────────────────────────
def _format_history(state: SessionState, max_turns: int = 3) -> str:
    turns = state.recent_turns(max_turns)
    if not turns:
        return "(no prior exchanges yet — start of session)"
    lines: list[str] = []
    for i, t in enumerate(turns, 1):
        prev_a = (t.answer or "").strip()
        if len(prev_a) > 400:
            prev_a = prev_a[:400].rstrip() + "…"
        lines.append(
            f"Turn {i}:\n  Student: {t.question.strip()}\n"
            f"  Aria: {prev_a or '(streaming…)'}"
        )
    return "\n".join(lines)


def _format_rag_chunks(chunks: list[Chunk]) -> str:
    if not chunks:
        return "(no relevant passages retrieved)"
    parts: list[str] = []
    for i, c in enumerate(chunks, 1):
        body = c.text.strip()
        if len(body) > 800:
            body = body[:800].rstrip() + "…"
        parts.append(f"[passage {i}]\n{body}")
    return "\n\n".join(parts)


def RAG_QUESTION_PROMPT(
    state: SessionState,
    question: str,
    retrieved_chunks: list[Chunk],
) -> str:
    """User-slot prompt for a free-form question with RAG context.

    When ``retrieved_chunks`` is empty, the caller (B3) should fall back to
    the existing ``QUESTION_PROMPT`` path — this prompt assumes at least one
    passage is present and tells the model to anchor on it.
    """
    topic = state.topic_name or state.topic_id or "(unspecified)"
    signals = state.student_signals or {}
    last_reaction = signals.get("last_reaction") or "none"

    return (
        f"{SOCRATIC_RULES}\n\n"
        "SOURCE PASSAGES (these are what we just covered — anchor your "
        "reply here, not generic knowledge):\n"
        f"{_format_rag_chunks(retrieved_chunks)}\n\n"
        f"SESSION CONTEXT:\n"
        f"- Topic: {topic}\n"
        f"- Step index: {state.step_idx}\n"
        f"- Hint level used so far (0=none, 3=lots): {state.hint_level}\n"
        f"- Last student reaction: {last_reaction}\n"
        f"- Recent transcript:\n{_format_history(state)}\n\n"
        f'The student just asked: "{question.strip()}"\n\n'
        "Respond Socratically. Reference the source passages above when "
        "forming your hint — paraphrase, do not quote verbatim. Do not "
        "introduce concepts that aren't grounded in those passages. ONE "
        "small nudge, end with a question. 2–4 sentences."
    )


__all__ = [
    "LESSON_GENERATION_SYSTEM_PROMPT",
    "LESSON_GENERATION_USER_PROMPT",
    "RAG_QUESTION_PROMPT",
]
