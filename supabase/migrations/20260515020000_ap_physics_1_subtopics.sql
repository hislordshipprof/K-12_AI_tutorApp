-- AP Physics 1 — CED 2024 sub-topic expansion.
--
-- Adds 2 sub-topics per unit so the dashboard outline shows hierarchy
-- instead of one identically-named row per expanded unit. The existing
-- per-unit topic (n=1) is renamed to "<Unit> — Overview" and keeps its
-- generated lesson + quiz content.
--
-- The new sub-topic rows start empty; bulk_subtopics_phys1.ps1 runs the
-- ingest + generate + quiz pipeline to populate them.

-- 1. Rename the existing per-unit topics so the unit + topic don't read
--    as duplicates side-by-side. Hard-coded by topic_id because these are
--    seed UUIDs that don't change.
update topics set name = 'Kinematics — Overview'                       where id = 'fcff4b99-92d6-4d5e-a9f2-b86adb15fb5c';
update topics set name = 'Force & Translational Dynamics — Overview'   where id = '854b3b40-4aaf-428a-81b3-fefc12813bae';
update topics set name = 'Work, Energy, and Power — Overview'          where id = 'b0498d5f-45fe-4a31-a451-2125353afc93';
update topics set name = 'Linear Momentum — Overview'                  where id = 'cdc272cd-729f-4bb3-9237-bf4c5c6249fc';
update topics set name = 'Torque & Rotational Dynamics — Overview'     where id = '7aa7075e-78d9-4623-a7db-0c73401bb9bb';
update topics set name = 'Rotating Systems — Overview'                 where id = 'ddcf647f-c4f0-4eec-87d4-c30f258a0d56';
update topics set name = 'Oscillations — Overview'                     where id = '4f66fec8-6b34-4149-bf15-aa16c7f51fe1';
update topics set name = 'Fluids — Overview'                           where id = '12ecfab6-b6ca-4db7-a0ef-73c6b6aac255';

-- 2. Insert sub-topic rows at n=2..N for each unit. Idempotent via
--    `where not exists` so re-running the migration is harmless.
insert into topics (unit_id, n, name, duration_min, sort_order)
select 'ef0cdeda-3e6c-4602-9f4d-9af598d47e05', 2, 'Position, Velocity & Acceleration', 12, 2
 where not exists (select 1 from topics where unit_id = 'ef0cdeda-3e6c-4602-9f4d-9af598d47e05' and n = 2);
insert into topics (unit_id, n, name, duration_min, sort_order)
select 'ef0cdeda-3e6c-4602-9f4d-9af598d47e05', 3, 'Projectile Motion', 14, 3
 where not exists (select 1 from topics where unit_id = 'ef0cdeda-3e6c-4602-9f4d-9af598d47e05' and n = 3);

insert into topics (unit_id, n, name, duration_min, sort_order)
select 'dbc6fd1d-823e-484b-9163-9ea7fb490de5', 2, 'Newton''s Laws & Free-Body Diagrams', 13, 2
 where not exists (select 1 from topics where unit_id = 'dbc6fd1d-823e-484b-9163-9ea7fb490de5' and n = 2);
insert into topics (unit_id, n, name, duration_min, sort_order)
select 'dbc6fd1d-823e-484b-9163-9ea7fb490de5', 3, 'Friction & Circular Motion', 14, 3
 where not exists (select 1 from topics where unit_id = 'dbc6fd1d-823e-484b-9163-9ea7fb490de5' and n = 3);

insert into topics (unit_id, n, name, duration_min, sort_order)
select '1cae8004-f125-45dc-af6c-be4b7b819776', 2, 'Work & Kinetic Energy', 12, 2
 where not exists (select 1 from topics where unit_id = '1cae8004-f125-45dc-af6c-be4b7b819776' and n = 2);
insert into topics (unit_id, n, name, duration_min, sort_order)
select '1cae8004-f125-45dc-af6c-be4b7b819776', 3, 'Potential Energy & Conservation', 13, 3
 where not exists (select 1 from topics where unit_id = '1cae8004-f125-45dc-af6c-be4b7b819776' and n = 3);

insert into topics (unit_id, n, name, duration_min, sort_order)
select 'ff490033-a498-4383-9f27-72052f54a61e', 2, 'Impulse & Momentum', 12, 2
 where not exists (select 1 from topics where unit_id = 'ff490033-a498-4383-9f27-72052f54a61e' and n = 2);
insert into topics (unit_id, n, name, duration_min, sort_order)
select 'ff490033-a498-4383-9f27-72052f54a61e', 3, 'Collisions & Conservation of Momentum', 14, 3
 where not exists (select 1 from topics where unit_id = 'ff490033-a498-4383-9f27-72052f54a61e' and n = 3);

insert into topics (unit_id, n, name, duration_min, sort_order)
select 'c542f11b-2fc9-4fb4-bc0e-6b1265747321', 2, 'Rotational Kinematics & Torque', 13, 2
 where not exists (select 1 from topics where unit_id = 'c542f11b-2fc9-4fb4-bc0e-6b1265747321' and n = 2);
insert into topics (unit_id, n, name, duration_min, sort_order)
select 'c542f11b-2fc9-4fb4-bc0e-6b1265747321', 3, 'Rotational Newton''s 2nd Law', 14, 3
 where not exists (select 1 from topics where unit_id = 'c542f11b-2fc9-4fb4-bc0e-6b1265747321' and n = 3);

insert into topics (unit_id, n, name, duration_min, sort_order)
select 'f0bfcb02-325e-4cbb-814d-d87b2e57aae7', 2, 'Rotational Kinetic Energy', 12, 2
 where not exists (select 1 from topics where unit_id = 'f0bfcb02-325e-4cbb-814d-d87b2e57aae7' and n = 2);
insert into topics (unit_id, n, name, duration_min, sort_order)
select 'f0bfcb02-325e-4cbb-814d-d87b2e57aae7', 3, 'Angular Momentum & Its Conservation', 13, 3
 where not exists (select 1 from topics where unit_id = 'f0bfcb02-325e-4cbb-814d-d87b2e57aae7' and n = 3);

insert into topics (unit_id, n, name, duration_min, sort_order)
select '66ea7494-947d-4c2d-aa38-069ff354ae3c', 2, 'Simple Harmonic Motion', 13, 2
 where not exists (select 1 from topics where unit_id = '66ea7494-947d-4c2d-aa38-069ff354ae3c' and n = 2);
insert into topics (unit_id, n, name, duration_min, sort_order)
select '66ea7494-947d-4c2d-aa38-069ff354ae3c', 3, 'Period & Energy of SHM', 12, 3
 where not exists (select 1 from topics where unit_id = '66ea7494-947d-4c2d-aa38-069ff354ae3c' and n = 3);

insert into topics (unit_id, n, name, duration_min, sort_order)
select '48322d0a-6867-4219-a8e4-84a534d642eb', 2, 'Density & Pressure', 12, 2
 where not exists (select 1 from topics where unit_id = '48322d0a-6867-4219-a8e4-84a534d642eb' and n = 2);
insert into topics (unit_id, n, name, duration_min, sort_order)
select '48322d0a-6867-4219-a8e4-84a534d642eb', 3, 'Buoyancy & Bernoulli', 13, 3
 where not exists (select 1 from topics where unit_id = '48322d0a-6867-4219-a8e4-84a534d642eb' and n = 3);
