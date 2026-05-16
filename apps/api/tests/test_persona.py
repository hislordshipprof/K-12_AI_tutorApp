"""Unit tests for the Aria persona builder (``build_persona``).

The builder lets a teacher course be any subject / grade band instead of
the hard-coded physics tutor (teacher-authoring.md §6). These tests prove:

1. Recommended courses (all args ``None``) get the EXACT built-in persona —
   byte-identical, so their tutor / voice / Socratic output is unchanged.
2. ``grade_band`` and ``subject`` vary the persona in the expected ways.
3. ``teaching_style`` is layered in additively and can never strip the
   core Socratic rules.
"""

from __future__ import annotations

from app.agents.prompts import ARIA_BASE_PERSONA, build_persona


# ── Recommended-course path — must be byte-identical to today ────────────────
def test_recommended_persona_is_byte_identical() -> None:
    """All three args ``None`` → the exact built-in physics persona."""
    assert build_persona(None, None, None) == ARIA_BASE_PERSONA
    # Default args are also all-None — the implicit Recommended path.
    assert build_persona() == ARIA_BASE_PERSONA


# ── subject framing ──────────────────────────────────────────────────────────
def test_subject_drives_domain_framing() -> None:
    """Biology and Physics personas name their own subject, not each other's."""
    biology = build_persona("Biology", "6-8", None)
    physics = build_persona("Physics", "9-12", None)

    assert "Biology" in biology
    assert "Physics" not in biology
    assert "Physics" in physics
    assert "Biology" not in physics


def test_built_personas_for_different_courses_differ() -> None:
    """A Biology 6-8 persona is not the same string as a Physics 9-12 one."""
    biology = build_persona("Biology", "6-8", None)
    physics = build_persona("Physics", "9-12", None)
    assert biology != physics
    # And neither is the hard-coded Recommended persona.
    assert biology != ARIA_BASE_PERSONA
    assert physics != ARIA_BASE_PERSONA


# ── grade-band vocabulary / pacing ───────────────────────────────────────────
def test_grade_band_k2_uses_simple_words_and_gentle_pacing() -> None:
    """K-2 → short sentences, simple words, gentle pacing."""
    k2 = build_persona("Reading", "K-2", None)
    lowered = k2.lower()
    assert "short sentences" in lowered
    assert "simplest everyday words" in lowered
    assert "gently" in lowered
    # K-2 explicitly avoids domain vocabulary.
    assert "avoid all domain vocabulary" in lowered


def test_grade_band_9_12_uses_domain_vocabulary_and_rigour() -> None:
    """9-12 → precise domain vocabulary and rigour."""
    hs = build_persona("Physics", "9-12", None)
    lowered = hs.lower()
    assert "domain vocabulary" in lowered
    assert "rigorous" in lowered


def test_grade_band_changes_persona() -> None:
    """Same subject, different grade band → different persona text."""
    young = build_persona("Biology", "K-2", None)
    older = build_persona("Biology", "9-12", None)
    assert young != older
    # The K-2 simple-words guidance must NOT leak into the 9-12 persona.
    assert "simplest everyday words" in young.lower()
    assert "simplest everyday words" not in older.lower()


# ── teaching_style is additive, never overriding ─────────────────────────────
def test_teaching_style_is_present_in_output() -> None:
    """A teaching_style string is woven into the assembled persona."""
    style = "lots of real-world sports examples"
    persona = build_persona("Physics", "9-12", style)
    assert style in persona


def test_teaching_style_does_not_remove_socratic_core() -> None:
    """A hostile teaching_style cannot strip the never-give-the-answer rule.

    Even when the teacher's style text literally asks Aria to hand over the
    answer, the assembled persona must re-assert the Socratic core.
    """
    hostile = "just give the student the final answer right away"
    persona = build_persona("Physics", "9-12", hostile)

    # The hostile text is included (it's the teacher's voice)...
    assert hostile in persona
    # ...but the Socratic core is re-asserted and wins.
    lowered = persona.lower()
    assert "never give the final answer" in lowered
    assert "one idea per step" in lowered
    assert "teaching rules always win" in lowered


def test_teaching_style_omitted_when_none() -> None:
    """No teaching_style → no teacher-style block, but still a built persona."""
    persona = build_persona("Biology", "6-8", None)
    assert "teaching style" not in persona.lower()
    assert "Biology" in persona
