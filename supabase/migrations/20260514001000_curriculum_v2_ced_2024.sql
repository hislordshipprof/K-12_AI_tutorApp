-- ============================================================================
-- K-12 AI Tutor — Curriculum v2: align with current College Board CEDs
-- ----------------------------------------------------------------------------
-- AP Physics 1 underwent a major redesign for Fall 2024:
--   - Waves & Sound, Electric Charge & Force, Circuits were REMOVED.
--   - Fluids was added.
--   - The mechanics core was expanded from 3 to 7 units.
-- AP Calc BC stays the same exam but our seed collapsed its 10 units to 6.
-- AP Biology already matches the CED — left alone.
--
-- This migration rewrites the unit tree for Physics 1 and Calc BC in place.
-- It preserves the demo lesson topic (`Wave Properties & Anatomy`) by
-- moving it under the new Oscillations unit and renaming it to reflect
-- what it actually teaches: amplitude / period / frequency — concepts that
-- ARE part of SHM in the 2024 Oscillations unit. The wavelength/v=fλ steps
-- in its content will be edited out in a follow-up content pass; this
-- migration keeps the FK chain intact so the existing test session and
-- frontend slug (`/classroom/wave-properties-anatomy`) keep working.
-- ============================================================================

-- ── AP Physics 1 ────────────────────────────────────────────────────────────

-- 1. Rename units 1–6 in place to the 2024 CED titles.
with c as (select id from public.courses where slug = 'ap-physics-1')
update public.units u
set name = case u.n
    when 1 then 'Kinematics'
    when 2 then 'Force & Translational Dynamics'
    when 3 then 'Work, Energy, and Power'
    when 4 then 'Linear Momentum'
    when 5 then 'Torque & Rotational Dynamics'
    when 6 then 'Energy & Momentum of Rotating Systems'
    else u.name
end
from c
where u.course_id = c.id and u.n between 1 and 6;

-- 2. Add the new units 7 & 8.
with c as (select id from public.courses where slug = 'ap-physics-1')
insert into public.units (course_id, n, name, sort_order)
select c.id, v.n, v.name, v.n
from c, (values (7, 'Oscillations'), (8, 'Fluids')) as v(n, name)
on conflict (course_id, n) do nothing;

-- 3. Drop the obsolete wave topics under what's now unit 4 EXCEPT the demo
--    lesson — we move that one. on delete cascade will tidy up any sessions
--    that referenced the discarded topics (none in practice).
with c as (select id from public.courses where slug = 'ap-physics-1'),
     u4 as (select u.id from public.units u, c where u.course_id = c.id and u.n = 4)
delete from public.topics
where unit_id in (select id from u4)
  and name <> 'Wave Properties & Anatomy';

-- 4. Move the demo lesson topic to the new Oscillations unit (unit 7) and
--    relabel it to match what it actually teaches under the 2024 CED.
--    The topic UUID is preserved so existing lesson_sessions FKs stay intact.
with c as (select id from public.courses where slug = 'ap-physics-1'),
     u7 as (select u.id from public.units u, c where u.course_id = c.id and u.n = 7)
update public.topics
set unit_id    = (select id from u7),
    n          = 1,
    sort_order = 1,
    name       = 'Oscillations: Amplitude, Period & Frequency',
    summary    = 'Simple harmonic motion: amplitude, period (T), frequency (f), '
                 'and why T = 1/f. Springs and pendulums as the canonical examples.'
where name = 'Wave Properties & Anatomy';


-- ── AP Calculus BC ──────────────────────────────────────────────────────────

-- Rename existing units 1–6 to the official 2024 CED titles.
with c as (select id from public.courses where slug = 'ap-calc-bc')
update public.units u
set name = case u.n
    when 1 then 'Limits & Continuity'
    when 2 then 'Differentiation: Definition & Fundamental Properties'
    when 3 then 'Differentiation: Composite, Implicit, & Inverse Functions'
    when 4 then 'Contextual Applications of Differentiation'
    when 5 then 'Analytical Applications of Differentiation'
    when 6 then 'Integration & Accumulation of Change'
    else u.name
end
from c
where u.course_id = c.id and u.n between 1 and 6;

-- Add the missing 7–10.
with c as (select id from public.courses where slug = 'ap-calc-bc')
insert into public.units (course_id, n, name, sort_order)
select c.id, v.n, v.name, v.n
from c, (values
    (7,  'Differential Equations'),
    (8,  'Applications of Integration'),
    (9,  'Parametric, Polar, & Vector-Valued Functions'),
    (10, 'Infinite Sequences & Series')
) as v(n, name)
on conflict (course_id, n) do nothing;


-- ── AP Biology ──────────────────────────────────────────────────────────────
-- Already matches the 2024 CED — no changes needed here.
