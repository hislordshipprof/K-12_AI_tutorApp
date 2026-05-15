-- ============================================================================
-- K-12 AI Tutor — Seed empty topic rows for every (course, unit) in mapping.yaml
-- ----------------------------------------------------------------------------
-- The B1 ingest CLI looks up `topics(id)` by walking
-- (course_slug → unit_n → topic_tail_keyword). The original seed only created
-- the Oscillations demo topic; B3's bulk ingest needs a target row for every
-- mapping.yaml entry so chunks can land somewhere.
--
-- We seed one *placeholder* topic per (course, unit) covered by mapping.yaml.
-- Names mirror the unit title (the resolver's keyword overlap finds it
-- because the topic tail and unit name share tokens). `content` stays NULL
-- until the generator fills it in.
--
-- Idempotent: `on conflict (unit_id, n) do nothing` so re-running the
-- migration in any environment is safe.
-- ============================================================================

with seed(course_slug, unit_n, name, summary) as (
  values
    -- ── AP Physics 1 ──────────────────────────────────────────────────
    ('ap-physics-1',  1, 'Kinematics',
       'One- and two-dimensional motion: displacement, velocity, acceleration, projectile motion.'),
    ('ap-physics-1',  2, 'Force & Translational Dynamics',
       'Newton''s three laws, free-body diagrams, friction, tension, and normal force.'),
    ('ap-physics-1',  3, 'Work, Energy, and Power',
       'Work–energy theorem, conservative and non-conservative forces, conservation of energy, power.'),
    ('ap-physics-1',  4, 'Linear Momentum',
       'Impulse, conservation of momentum, elastic and inelastic collisions in 1D and 2D.'),
    ('ap-physics-1',  5, 'Torque & Rotational Dynamics',
       'Equilibrium conditions, torque, angular kinematics, rotational inertia.'),
    ('ap-physics-1',  6, 'Energy & Momentum of Rotating Systems',
       'Rotational kinetic energy, angular momentum and its conservation.'),
    ('ap-physics-1',  8, 'Fluids',
       'Density, pressure, buoyancy (Archimedes), flow continuity, Bernoulli''s equation.'),

    -- ── AP Calculus BC ────────────────────────────────────────────────
    ('ap-calc-bc',    1, 'Limits & Continuity',
       'Intuitive and formal limit, limit laws, continuity, indeterminate forms.'),
    ('ap-calc-bc',    2, 'Differentiation: Definition & Fundamental Properties',
       'Derivative as a limit, basic differentiation rules, derivatives as rates of change.'),
    ('ap-calc-bc',    3, 'Differentiation: Composite, Implicit, & Inverse Functions',
       'Chain rule, implicit differentiation, derivatives of inverse, trig, exp, and log functions.'),
    ('ap-calc-bc',    4, 'Contextual Applications of Differentiation',
       'Related rates, linear approximations, L''Hôpital''s rule.'),
    ('ap-calc-bc',    5, 'Analytical Applications of Differentiation',
       'Extrema, Mean Value Theorem, shape of a graph, asymptotes, optimization.'),
    ('ap-calc-bc',    6, 'Integration & Accumulation of Change',
       'Definite integral, Fundamental Theorem of Calculus, substitution.'),
    ('ap-calc-bc',    7, 'Differential Equations',
       'Slope fields, separable equations, the logistic equation, first-order linear ODEs.'),
    ('ap-calc-bc',    8, 'Applications of Integration',
       'Area between curves, volumes by slicing and shells, arc length, physical applications.'),
    ('ap-calc-bc',    9, 'Parametric, Polar, & Vector-Valued Functions',
       'Parametric curves, calculus of parametric/polar, area and arc length in polar.'),
    ('ap-calc-bc',   10, 'Infinite Sequences & Series',
       'Sequences, series convergence tests, power series, Taylor and Maclaurin series.'),

    -- ── AP Biology ────────────────────────────────────────────────────
    ('ap-biology',    1, 'Chemistry of Life',
       'Atoms and bonding, water, carbon, biological macromolecules.'),
    ('ap-biology',    2, 'Cell Structure & Function',
       'Prokaryotic vs eukaryotic cells, organelles, membrane structure and transport.'),
    ('ap-biology',    3, 'Cellular Energetics',
       'Glycolysis, citric acid cycle, oxidative phosphorylation, photosynthesis.'),
    ('ap-biology',    4, 'Cell Communication & the Cell Cycle',
       'Signal reception, transduction, response; cell cycle and its regulation.'),
    ('ap-biology',    5, 'Heredity',
       'Mendelian inheritance, characteristics and traits, chromosomal basis of inheritance.'),
    ('ap-biology',    6, 'Gene Expression & Regulation',
       'Transcription, translation, gene regulation in prokaryotes and eukaryotes.'),
    ('ap-biology',    7, 'Natural Selection',
       'Evolution, speciation, population evolution and genetics.'),
    ('ap-biology',    8, 'Ecology',
       'Scope of ecology, biogeography, biomes, populations and communities.')
)
insert into public.topics (unit_id, n, name, summary, content, sort_order)
select u.id, 1, s.name, s.summary, null, 1
from seed s
join public.courses c on c.slug = s.course_slug
join public.units u on u.course_id = c.id and u.n = s.unit_n
on conflict (unit_id, n) do nothing;
