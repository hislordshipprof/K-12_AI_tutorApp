-- ============================================================================
-- K-12 AI Tutor — Seed Data
-- ----------------------------------------------------------------------------
-- Curriculum data only — no user-owned rows (those are seeded post-signup).
-- Idempotent: uses on conflict do nothing where possible.
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
-- AP Physics 1 — units & topics
-- ---------------------------------------------------------------------------
with c as (select id from public.courses where slug = 'ap-physics-1')
insert into public.units (course_id, n, name, sort_order)
select c.id, v.n, v.name, v.n
from c, (values
  (1, 'Kinematics'),
  (2, 'Forces & Newton''s Laws'),
  (3, 'Energy & Momentum'),
  (4, 'Waves & Sound'),
  (5, 'Electric Charge & Force'),
  (6, 'Circuits')
) as v(n, name)
on conflict (course_id, n) do nothing;

-- Unit 4 "Waves & Sound" — 7 topics, with the demo lesson content
-- on topic #2 "Wave Properties & Anatomy".
with u as (
  select t.id from public.units t
  join public.courses c on c.id = t.course_id
  where c.slug = 'ap-physics-1' and t.n = 4
)
insert into public.topics (unit_id, n, name, duration_min, summary, content, sort_order)
select u.id, v.n, v.name, v.duration_min, v.summary, v.content::jsonb, v.n
from u, (values
  (1, 'Introduction to Waves', 12,
   'What a wave is and why oscillation matters.',
   '[]'),
  (2, 'Wave Properties & Anatomy', 18,
   'Crests, troughs, amplitude, wavelength, frequency, period, and v = f·λ.',
   $json$[
     {"tts": "Preparing your lesson.",
      "html": "Preparing your lesson…",
      "dur": "00:00"},
     {"tts": "Every wave starts at a rest position — the line everything wobbles around.",
      "html": "Every wave starts at a <span class=\"hl-y\">rest position</span> — the line everything wobbles around.",
      "dur": "01:20"},
     {"tts": "Now I'll draw the wave. Watch how it oscillates above and below equilibrium.",
      "html": "Now I'll draw the wave. Watch how it oscillates <span class=\"hl-b\">above</span> and <span class=\"hl-p\">below</span> equilibrium.",
      "dur": "02:15"},
     {"tts": "The high points are crests, and the low points are troughs.",
      "html": "The high points are <span class=\"hl-y\">crests</span> and the low points are <span class=\"hl-p\">troughs</span>.",
      "dur": "03:40"},
     {"tts": "The amplitude is how far the wave goes from rest. It's the wave's energy.",
      "html": "The <span class=\"hl-p\">amplitude</span> is how far the wave goes from rest — it's the wave's <em>energy</em>.",
      "dur": "05:10"},
     {"tts": "One full cycle, crest to crest, is the wavelength. That lowercase lambda.",
      "html": "One full cycle, crest to crest, is the <span class=\"hl-g\">wavelength</span> — that lowercase λ.",
      "dur": "07:30"},
     {"tts": "How often a wave repeats is frequency. Its inverse is the period.",
      "html": "How often a wave repeats is <span class=\"hl-y\">frequency</span>. Its inverse is the <span class=\"hl-y\">period</span>.",
      "dur": "09:50"},
     {"tts": "Put it together: v equals f times lambda. Speed equals frequency times wavelength. That's the whole game.",
      "html": "Put it together: <span class=\"hl-y\">v = f · λ</span>. Speed equals frequency times wavelength. That's the whole game.",
      "dur": "12:40"}
   ]$json$),
  (3, 'Wave Speed & Medium', 14,
   'How the medium sets v, and why heavier strings sound lower.',
   '[]'),
  (4, 'Superposition & Interference', 20,
   'Constructive vs. destructive interference; beats.',
   '[]'),
  (5, 'Standing Waves', 16,
   'Nodes, antinodes, and the harmonics of strings & pipes.',
   '[]'),
  (6, 'Sound Waves & Doppler', 22,
   'Longitudinal pressure waves and frequency shift from motion.',
   '[]'),
  (7, 'Unit 4 Practice Exam', 45,
   'Mixed MCQ + FRQ on everything in Unit 4.',
   '[]')
) as v(n, name, duration_min, summary, content)
on conflict (unit_id, n) do nothing;

-- ---------------------------------------------------------------------------
-- AP Calculus BC — units only (no topic content)
-- ---------------------------------------------------------------------------
with c as (select id from public.courses where slug = 'ap-calc-bc')
insert into public.units (course_id, n, name, sort_order)
select c.id, v.n, v.name, v.n
from c, (values
  (1, 'Limits & Continuity'),
  (2, 'Differentiation'),
  (3, 'Applications of Derivatives'),
  (4, 'Integration'),
  (5, 'Differential Equations'),
  (6, 'Series & Sequences')
) as v(n, name)
on conflict (course_id, n) do nothing;

-- ---------------------------------------------------------------------------
-- AP Biology — units only
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
