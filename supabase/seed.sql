-- ============================================================================
-- K-12 AI Tutor — Seed Data
-- ----------------------------------------------------------------------------
-- Curriculum data only — no user-owned rows (those are seeded post-signup).
-- Idempotent: uses on conflict do nothing where possible.
--
-- Unit structures match the OFFICIAL College Board Course & Exam Descriptions
-- (CEDs) as of 2026-05-14:
--   AP Physics 1 — 2024 redesign (8 units; Waves/Sound/E&M moved to Physics 2).
--   AP Calc BC   — 10 units.
--   AP Biology   — 8 units.
-- The 20260514001000_curriculum_v2_ced_2024 migration brings existing rows
-- in line; this file is what a *fresh* `supabase db reset` recreates.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Courses
-- ---------------------------------------------------------------------------
insert into public.courses (slug, title, exam, color_gradient, icon_emoji, sort_order)
values
  ('ap-physics-1', 'AP Physics 1', 'AP',
   'linear-gradient(135deg,#1F4E7A 0%,#5B5BE5 100%)', '⚛️', 1),
  ('ap-calc-bc',   'AP Calculus BC', 'AP',
   'linear-gradient(135deg,#7A1F4E 0%,#E55B9C 100%)', '∫',  2),
  ('ap-biology',   'AP Biology', 'AP',
   'linear-gradient(135deg,#1F7A4E 0%,#5BE59C 100%)', '🧬', 3)
on conflict (slug) do nothing;

-- ---------------------------------------------------------------------------
-- AP Physics 1 — 2024 CED units & topics
-- ---------------------------------------------------------------------------
with c as (select id from public.courses where slug = 'ap-physics-1')
insert into public.units (course_id, n, name, sort_order)
select c.id, v.n, v.name, v.n
from c, (values
  (1, 'Kinematics'),
  (2, 'Force & Translational Dynamics'),
  (3, 'Work, Energy, and Power'),
  (4, 'Linear Momentum'),
  (5, 'Torque & Rotational Dynamics'),
  (6, 'Energy & Momentum of Rotating Systems'),
  (7, 'Oscillations'),
  (8, 'Fluids')
) as v(n, name)
on conflict (course_id, n) do nothing;

-- Unit 7 "Oscillations" — demo lesson on SHM amplitude/period/frequency.
-- The lesson content reuses the original Aria-voiced steps because SHM
-- shares amplitude/period/frequency vocabulary with the old "wave anatomy"
-- lesson. A follow-up content pass should drop the wavelength/v=fλ steps
-- (those are AP Physics 2 territory in the post-2024 CED).
with u as (
  select t.id from public.units t
  join public.courses c on c.id = t.course_id
  where c.slug = 'ap-physics-1' and t.n = 7
)
insert into public.topics (unit_id, n, name, duration_min, summary, content, sort_order)
select u.id, v.n, v.name, v.duration_min, v.summary, v.content::jsonb, v.n
from u, (values
  (1, 'Oscillations: Amplitude, Period & Frequency', 18,
   'Simple harmonic motion: amplitude, period (T), frequency (f), and why T = 1/f. Springs and pendulums as the canonical examples.',
   $json$[
     {"tts": "Preparing your lesson.",
      "html": "Preparing your lesson…",
      "dur": "00:00"},
     {"tts": "Every oscillation starts at a rest position — the line everything wobbles around.",
      "html": "Every oscillation starts at a <span class=\"hl-y\">rest position</span> — the line everything wobbles around.",
      "dur": "01:20"},
     {"tts": "Now I'll draw the motion. Watch how it oscillates above and below equilibrium.",
      "html": "Now I'll draw the motion. Watch how it oscillates <span class=\"hl-b\">above</span> and <span class=\"hl-p\">below</span> equilibrium.",
      "dur": "02:15"},
     {"tts": "The high points and low points are the extremes of the motion.",
      "html": "The high points and low points are the <span class=\"hl-y\">extremes</span> of the motion.",
      "dur": "03:40"},
     {"tts": "The amplitude is how far the system moves from rest. It's the oscillation's energy.",
      "html": "The <span class=\"hl-p\">amplitude</span> is how far the system moves from rest — it's the oscillation's <em>energy</em>.",
      "dur": "05:10"},
     {"tts": "One full back-and-forth cycle takes one period. Call it T.",
      "html": "One full back-and-forth cycle takes one <span class=\"hl-g\">period</span> — call it T.",
      "dur": "07:30"},
     {"tts": "How often it repeats is the frequency. Its inverse is the period.",
      "html": "How often it repeats is <span class=\"hl-y\">frequency</span>. Its inverse is the <span class=\"hl-y\">period</span>.",
      "dur": "09:50"},
     {"tts": "Put it together: T equals one over f. Period equals one divided by frequency. That's the whole game.",
      "html": "Put it together: <span class=\"hl-y\">T = 1 / f</span>. Period equals one divided by frequency. That's the whole game.",
      "dur": "12:40"}
   ]$json$)
) as v(n, name, duration_min, summary, content)
on conflict (unit_id, n) do nothing;

-- ---------------------------------------------------------------------------
-- AP Calculus BC — 2024 CED 10 units (no topic content yet)
-- ---------------------------------------------------------------------------
with c as (select id from public.courses where slug = 'ap-calc-bc')
insert into public.units (course_id, n, name, sort_order)
select c.id, v.n, v.name, v.n
from c, (values
  (1,  'Limits & Continuity'),
  (2,  'Differentiation: Definition & Fundamental Properties'),
  (3,  'Differentiation: Composite, Implicit, & Inverse Functions'),
  (4,  'Contextual Applications of Differentiation'),
  (5,  'Analytical Applications of Differentiation'),
  (6,  'Integration & Accumulation of Change'),
  (7,  'Differential Equations'),
  (8,  'Applications of Integration'),
  (9,  'Parametric, Polar, & Vector-Valued Functions'),
  (10, 'Infinite Sequences & Series')
) as v(n, name)
on conflict (course_id, n) do nothing;

-- ---------------------------------------------------------------------------
-- AP Biology — 2024 CED 8 units (already matched; left for fresh checkouts)
-- ---------------------------------------------------------------------------
with c as (select id from public.courses where slug = 'ap-biology')
insert into public.units (course_id, n, name, sort_order)
select c.id, v.n, v.name, v.n
from c, (values
  (1, 'Chemistry of Life'),
  (2, 'Cell Structure & Function'),
  (3, 'Cellular Energetics'),
  (4, 'Cell Communication & Cycle'),
  (5, 'Heredity'),
  (6, 'Gene Expression & Regulation'),
  (7, 'Natural Selection'),
  (8, 'Ecology')
) as v(n, name)
on conflict (course_id, n) do nothing;
