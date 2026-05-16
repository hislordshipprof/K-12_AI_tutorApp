-- ============================================================================
-- Task 1.1 + 1.2 — Teacher-authored courses: full §4 schema + RLS
-- ----------------------------------------------------------------------------
-- Implements docs/teacher-authoring.md §4 ("Data model") and its "RLS
-- (defense-in-depth)" sketch, plus the §13 cascade rules.
--
-- Scope notes:
--   * `profiles.role` and the `teacher_invites` table are NOT defined here —
--     they were already shipped by 20260515030000_admin_role_teacher_invites
--     (task 0.3). §4 lists them; this migration deliberately omits them.
--   * The new content/teacher tables (lesson_materials, material_pages,
--     topic_pages, topic_versions, unit_segmentations, pipeline_jobs, the
--     version-scoped quiz_questions FK) cascade ON DELETE per §13. Teacher
--     account rows (classes.teacher_id, courses.owner_id) use a plain FK with
--     NO cascade action: §13 says a deactivated teacher is FROZEN, not
--     deleted, so a profile delete should be BLOCKED rather than silently
--     erase or orphan a course tree.
--
-- Every statement is idempotent (`create table if not exists`,
-- `add column if not exists`, `create index if not exists`, guarded `do $$`
-- blocks for constraints, `drop policy if exists` before `create policy`,
-- `create or replace function`) so the whole file is safe to re-run.
-- ============================================================================


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ PART A — NEW TABLES                                                       ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
-- Order matters for FKs. `topic_versions` is created before the
-- `topics.active_version_id` column so the circular reference
-- (topics → topic_versions → topics) can be resolved without a forward ref:
-- topic_versions.topic_id points at the already-existing `topics`, then the
-- `topics.active_version_id` FK is added afterwards (PART B / guarded block).

-- ---------------------------------------------------------------------------
-- classes — a teacher's section; students join with a code.
-- ---------------------------------------------------------------------------
create table if not exists public.classes (
  id          uuid primary key default gen_random_uuid(),
  teacher_id  uuid references public.profiles(id),          -- §13: no cascade — frozen, not deleted
  name        text,
  subject     text,
  join_code   text unique,
  archived    boolean default false,
  created_at  timestamptz not null default now()
);

create index if not exists idx_classes_teacher on public.classes(teacher_id);

-- ---------------------------------------------------------------------------
-- class_members — a student belongs to a class (teacher-approved join).
-- ---------------------------------------------------------------------------
create table if not exists public.class_members (
  class_id      uuid references public.classes(id) on delete cascade,
  student_id    uuid references public.profiles(id) on delete cascade,  -- student-owned row
  status        text not null default 'pending',           -- 'pending' | 'active'
  requested_at  timestamptz,
  approved_by   uuid references public.profiles(id) on delete set null, -- audit ref
  approved_at   timestamptz,
  primary key (class_id, student_id)
);

create index if not exists idx_class_members_student on public.class_members(student_id);
create index if not exists idx_class_members_approved_by on public.class_members(approved_by);

-- ---------------------------------------------------------------------------
-- class_courses — which teacher courses a class can see.
-- ---------------------------------------------------------------------------
create table if not exists public.class_courses (
  class_id     uuid references public.classes(id) on delete cascade,
  course_id    uuid references public.courses(id) on delete cascade,
  assigned_at  timestamptz,
  primary key (class_id, course_id)
);

create index if not exists idx_class_courses_course on public.class_courses(course_id);

-- ---------------------------------------------------------------------------
-- lesson_materials — the teacher's raw uploads, at the UNIT level.
-- ---------------------------------------------------------------------------
create table if not exists public.lesson_materials (
  id                 uuid primary key default gen_random_uuid(),
  unit_id            uuid references public.units(id) on delete cascade,
  kind               text,                                 -- 'notes' | 'slides' | 'practice'
  storage_path       text,
  normalized_pdf     text,
  filename           text,
  mime               text,
  conversion_status  text,                                  -- 'pending'|'converting'|'converted'|'failed'
  uploaded_by        uuid references public.profiles(id) on delete set null,  -- audit ref
  uploaded_at        timestamptz
);

create index if not exists idx_lesson_materials_unit on public.lesson_materials(unit_id);
create index if not exists idx_lesson_materials_uploaded_by on public.lesson_materials(uploaded_by);

-- ---------------------------------------------------------------------------
-- material_pages — one rendered PNG per displayed page of a material.
-- ---------------------------------------------------------------------------
create table if not exists public.material_pages (
  material_id  uuid references public.lesson_materials(id) on delete cascade,
  idx          int,
  image_path   text,
  primary key (material_id, idx)
);

-- ---------------------------------------------------------------------------
-- unit_segmentations — unit-level multimodal comprehension + proposed breakdown.
-- ---------------------------------------------------------------------------
create table if not exists public.unit_segmentations (
  id             uuid primary key default gen_random_uuid(),
  unit_id        uuid references public.units(id) on delete cascade,
  comprehension  jsonb,
  proposed       jsonb,
  status         text,                                      -- 'proposed' | 'confirmed'
  created_at     timestamptz
);

create index if not exists idx_unit_segmentations_unit on public.unit_segmentations(unit_id);

-- ---------------------------------------------------------------------------
-- topic_versions — generated-lesson history. Created BEFORE the
-- topics.active_version_id column so the circular FK resolves cleanly.
-- ---------------------------------------------------------------------------
create table if not exists public.topic_versions (
  id          uuid primary key default gen_random_uuid(),
  topic_id    uuid references public.topics(id) on delete cascade,
  content     jsonb,
  label       text,
  created_at  timestamptz,
  created_by  uuid references public.profiles(id) on delete set null    -- audit ref
);

create index if not exists idx_topic_versions_topic on public.topic_versions(topic_id);
create index if not exists idx_topic_versions_created_by on public.topic_versions(created_by);

-- ---------------------------------------------------------------------------
-- topic_pages — which rendered pages a topic uses (may span many materials).
-- ---------------------------------------------------------------------------
create table if not exists public.topic_pages (
  id           uuid primary key default gen_random_uuid(),
  topic_id     uuid references public.topics(id) on delete cascade,
  material_id  uuid references public.lesson_materials(id) on delete cascade,
  page_idx     int,
  role         text,                                        -- 'slide' | 'figure'
  ord          int,
  unique (topic_id, material_id, page_idx)
);

create index if not exists idx_topic_pages_topic on public.topic_pages(topic_id);
create index if not exists idx_topic_pages_material on public.topic_pages(material_id);

-- ---------------------------------------------------------------------------
-- pipeline_jobs — async work (segment / generate); polled by the board.
-- ---------------------------------------------------------------------------
create table if not exists public.pipeline_jobs (
  id          uuid primary key default gen_random_uuid(),
  kind        text,                                         -- 'segment' | 'generate'
  unit_id     uuid references public.units(id) on delete cascade,
  topic_id    uuid references public.topics(id) on delete cascade,
  status      text,                                         -- 'queued'|'running'|'succeeded'|'failed'
  stage       text,
  error       text,
  created_at  timestamptz,
  updated_at  timestamptz
);

create index if not exists idx_pipeline_jobs_unit on public.pipeline_jobs(unit_id);
create index if not exists idx_pipeline_jobs_topic on public.pipeline_jobs(topic_id);


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ PART B — NEW COLUMNS ON EXISTING TABLES                                   ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

-- ---------------------------------------------------------------------------
-- courses — ownership + persona parameters (§4).
-- ---------------------------------------------------------------------------
alter table public.courses
  add column if not exists owner_id       uuid references public.profiles(id);  -- §13: no cascade
alter table public.courses
  add column if not exists origin         text not null default 'recommended'; -- 'recommended' | 'teacher'
alter table public.courses
  add column if not exists subject        text;
alter table public.courses
  add column if not exists grade_band     text;                                -- 'K-2'|'3-5'|'6-8'|'9-12'
alter table public.courses
  add column if not exists teaching_style text;

create index if not exists idx_courses_owner on public.courses(owner_id);

-- ---------------------------------------------------------------------------
-- topics — authoring status + design notes + active version + quiz source.
-- ---------------------------------------------------------------------------
alter table public.topics
  add column if not exists status            text not null default 'published'; -- 'draft' | 'published'
alter table public.topics
  add column if not exists design_notes      text;
alter table public.topics
  add column if not exists active_version_id uuid;                               -- FK added below
alter table public.topics
  add column if not exists quiz_source       text not null default 'auto';       -- 'auto' | 'practice'

-- Circular-FK resolution: topics.active_version_id -> topic_versions(id).
-- The column is added unconstrained above; the FK constraint is attached here
-- only if it does not already exist, so the migration stays idempotent.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'topics_active_version_id_fkey'
  ) then
    alter table public.topics
      add constraint topics_active_version_id_fkey
      foreign key (active_version_id)
      references public.topic_versions(id) on delete set null;
  end if;
end $$;

create index if not exists idx_topics_active_version on public.topics(active_version_id);

-- ---------------------------------------------------------------------------
-- topic_progress — the lesson version this progress was made against.
-- ---------------------------------------------------------------------------
alter table public.topic_progress
  add column if not exists active_version_id uuid;                               -- FK added below

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'topic_progress_active_version_id_fkey'
  ) then
    alter table public.topic_progress
      add constraint topic_progress_active_version_id_fkey
      foreign key (active_version_id)
      references public.topic_versions(id) on delete set null;
  end if;
end $$;

create index if not exists idx_topic_progress_active_version
  on public.topic_progress(active_version_id);

-- ---------------------------------------------------------------------------
-- quiz_questions — version-scoping for teacher courses (§4 / §6 "Quiz").
-- ---------------------------------------------------------------------------
alter table public.quiz_questions
  add column if not exists topic_version_id uuid;                                -- FK added below

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'quiz_questions_topic_version_id_fkey'
  ) then
    alter table public.quiz_questions
      add constraint quiz_questions_topic_version_id_fkey
      foreign key (topic_version_id)
      references public.topic_versions(id) on delete cascade;                    -- §13: version-scoped, cascades
  end if;
end $$;

create index if not exists idx_quiz_questions_topic_version
  on public.quiz_questions(topic_version_id);


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ PART C — RLS HELPER FUNCTIONS                                             ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
-- The teacher-content tables (lesson_materials, material_pages, topic_pages,
-- unit_segmentations, pipeline_jobs) have no teacher_id column. RLS reaches
-- the owning teacher by joining up the curriculum tree to `courses.owner_id`.
-- That join is implemented ONCE here and reused across every policy.
--
-- `security definer` + `set search_path = public` lets the function read the
-- curriculum tables regardless of the caller's RLS, and pins name resolution.

-- True when auth.uid() owns the course that `p_unit_id` rolls up to.
create or replace function public.is_unit_owner(p_unit_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.units u
    join public.courses c on c.id = u.course_id
    where u.id = p_unit_id
      and c.owner_id = auth.uid()
  );
$$;

-- True when auth.uid() owns the course that `p_topic_id` rolls up to
-- (topic -> unit -> course.owner_id).
create or replace function public.is_topic_owner(p_topic_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.topics t
    join public.units u on u.id = t.unit_id
    join public.courses c on c.id = u.course_id
    where t.id = p_topic_id
      and c.owner_id = auth.uid()
  );
$$;

-- True when auth.uid() is an ACTIVE member of a class that `p_course_id`
-- is assigned to (class_members.status='active' -> class_courses).
create or replace function public.is_active_member_of_course(p_course_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.class_courses cc
    join public.class_members cm on cm.class_id = cc.class_id
    where cc.course_id = p_course_id
      and cm.student_id = auth.uid()
      and cm.status = 'active'
  );
$$;

-- True when the caller's profile role is 'admin'.
create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.profiles p
    where p.id = auth.uid() and p.role = 'admin'
  );
$$;

-- ── class-membership helpers ────────────────────────────────────────────────
-- `classes` and `class_members` reference each other (a teacher sees their
-- class's members; a student sees a class they belong to). If those policies
-- queried each other's table directly, Postgres RLS would recurse infinitely
-- (42P17). These SECURITY DEFINER helpers do the cross-table lookup OUTSIDE
-- RLS, so each policy stays a single non-recursive predicate.

-- True when auth.uid() is the teacher who owns the class.
create or replace function public.is_class_teacher(p_class_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.classes
    where id = p_class_id and teacher_id = auth.uid()
  );
$$;

-- True when auth.uid() holds ANY membership (pending or active) in the class.
create or replace function public.is_class_member(p_class_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.class_members
    where class_id = p_class_id and student_id = auth.uid()
  );
$$;

-- True when auth.uid() is an ACTIVE member of the class.
create or replace function public.is_active_class_member(p_class_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.class_members
    where class_id = p_class_id and student_id = auth.uid() and status = 'active'
  );
$$;


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ PART D — RLS: REPLACE THE WORLD-READABLE CURRICULUM POLICIES              ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
-- 20260514000100_rls.sql made courses/units/topics readable by ANY
-- authenticated user. With teacher courses that is wrong: a teacher's
-- unpublished / un-assigned content must not leak. The replacement rule:
--   * Recommended content (origin='recommended') stays world-readable.
--   * Teacher content is visible only to its owner-teacher, to an admin, and
--     (for published topics / assigned courses+units) to students with an
--     ACTIVE class membership.
-- Teachers also get INSERT/UPDATE/DELETE on their own course tree.

-- ── courses ────────────────────────────────────────────────────────────────
alter table public.courses enable row level security;

drop policy if exists "courses_read_all" on public.courses;

-- Recommended courses: world-readable to any authenticated user (as before).
create policy "courses_read_recommended" on public.courses
  for select to authenticated
  using (origin = 'recommended');

-- Teacher courses: owner sees own; active members see assigned; admin sees all.
create policy "courses_read_teacher" on public.courses
  for select to authenticated
  using (
    origin = 'teacher'
    and (
      owner_id = auth.uid()
      or public.is_admin()
      or public.is_active_member_of_course(id)
    )
  );

-- Teachers author their own courses.
drop policy if exists "courses_teacher_insert" on public.courses;
drop policy if exists "courses_teacher_update" on public.courses;
drop policy if exists "courses_teacher_delete" on public.courses;

create policy "courses_teacher_insert" on public.courses
  for insert to authenticated
  with check (origin = 'teacher' and owner_id = auth.uid());

create policy "courses_teacher_update" on public.courses
  for update to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

create policy "courses_teacher_delete" on public.courses
  for delete to authenticated
  using (owner_id = auth.uid());

-- ── units ──────────────────────────────────────────────────────────────────
alter table public.units enable row level security;

drop policy if exists "units_read_all" on public.units;

-- A unit inherits the visibility of its course.
create policy "units_read_recommended" on public.units
  for select to authenticated
  using (
    exists (
      select 1 from public.courses c
      where c.id = units.course_id and c.origin = 'recommended'
    )
  );

create policy "units_read_teacher" on public.units
  for select to authenticated
  using (
    exists (
      select 1 from public.courses c
      where c.id = units.course_id
        and c.origin = 'teacher'
        and (
          c.owner_id = auth.uid()
          or public.is_admin()
          or public.is_active_member_of_course(c.id)
        )
    )
  );

drop policy if exists "units_teacher_insert" on public.units;
drop policy if exists "units_teacher_update" on public.units;
drop policy if exists "units_teacher_delete" on public.units;

create policy "units_teacher_insert" on public.units
  for insert to authenticated
  with check (
    exists (
      select 1 from public.courses c
      where c.id = units.course_id and c.owner_id = auth.uid()
    )
  );

create policy "units_teacher_update" on public.units
  for update to authenticated
  using (
    exists (
      select 1 from public.courses c
      where c.id = units.course_id and c.owner_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.courses c
      where c.id = units.course_id and c.owner_id = auth.uid()
    )
  );

create policy "units_teacher_delete" on public.units
  for delete to authenticated
  using (
    exists (
      select 1 from public.courses c
      where c.id = units.course_id and c.owner_id = auth.uid()
    )
  );

-- ── topics ─────────────────────────────────────────────────────────────────
alter table public.topics enable row level security;

drop policy if exists "topics_read_all" on public.topics;

-- Topics of Recommended courses: world-readable (unchanged behaviour).
create policy "topics_read_recommended" on public.topics
  for select to authenticated
  using (
    exists (
      select 1
      from public.units u
      join public.courses c on c.id = u.course_id
      where u.id = topics.unit_id and c.origin = 'recommended'
    )
  );

-- Topics of teacher courses: owner sees all; admin sees all; an active-member
-- student sees ONLY 'published' topics of an assigned course.
create policy "topics_read_teacher" on public.topics
  for select to authenticated
  using (
    exists (
      select 1
      from public.units u
      join public.courses c on c.id = u.course_id
      where u.id = topics.unit_id
        and c.origin = 'teacher'
        and (
          c.owner_id = auth.uid()
          or public.is_admin()
          or (
            topics.status = 'published'
            and public.is_active_member_of_course(c.id)
          )
        )
    )
  );

drop policy if exists "topics_teacher_insert" on public.topics;
drop policy if exists "topics_teacher_update" on public.topics;
drop policy if exists "topics_teacher_delete" on public.topics;

create policy "topics_teacher_insert" on public.topics
  for insert to authenticated
  with check (public.is_unit_owner(unit_id));

create policy "topics_teacher_update" on public.topics
  for update to authenticated
  using (public.is_unit_owner(unit_id))
  with check (public.is_unit_owner(unit_id));

create policy "topics_teacher_delete" on public.topics
  for delete to authenticated
  using (public.is_unit_owner(unit_id));


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ PART E — RLS: NEW TABLES                                                  ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
-- Every new table enables RLS. The API talks to Supabase mostly via the
-- service role (which bypasses RLS); these policies are defense-in-depth for
-- any direct anon-key + JWT access by a student or teacher.

-- ── classes ────────────────────────────────────────────────────────────────
alter table public.classes enable row level security;

drop policy if exists "classes_teacher_select" on public.classes;
drop policy if exists "classes_member_select"  on public.classes;
drop policy if exists "classes_admin_select"   on public.classes;
drop policy if exists "classes_teacher_insert" on public.classes;
drop policy if exists "classes_teacher_update" on public.classes;
drop policy if exists "classes_teacher_delete" on public.classes;

-- A teacher sees (and manages) only their own classes.
create policy "classes_teacher_select" on public.classes
  for select to authenticated
  using (teacher_id = auth.uid());

-- A student sees a class they hold a membership in (any status) — so the
-- dashboard can show an "awaiting approval" pending class. Routed through the
-- definer helper so this does not recurse into class_members RLS.
create policy "classes_member_select" on public.classes
  for select to authenticated
  using (public.is_class_member(id));

create policy "classes_admin_select" on public.classes
  for select to authenticated
  using (public.is_admin());

create policy "classes_teacher_insert" on public.classes
  for insert to authenticated
  with check (teacher_id = auth.uid());

create policy "classes_teacher_update" on public.classes
  for update to authenticated
  using (teacher_id = auth.uid())
  with check (teacher_id = auth.uid());

create policy "classes_teacher_delete" on public.classes
  for delete to authenticated
  using (teacher_id = auth.uid());

-- ── class_members ──────────────────────────────────────────────────────────
alter table public.class_members enable row level security;

drop policy if exists "class_members_student_select" on public.class_members;
drop policy if exists "class_members_teacher_select" on public.class_members;
drop policy if exists "class_members_admin_select"   on public.class_members;
drop policy if exists "class_members_student_insert" on public.class_members;
drop policy if exists "class_members_teacher_update" on public.class_members;
drop policy if exists "class_members_teacher_delete" on public.class_members;
drop policy if exists "class_members_student_delete" on public.class_members;

-- A student reads their own memberships.
create policy "class_members_student_select" on public.class_members
  for select to authenticated
  using (student_id = auth.uid());

-- The class's teacher reads every member of their own classes. Routed through
-- the definer helper so this does not recurse into classes RLS.
create policy "class_members_teacher_select" on public.class_members
  for select to authenticated
  using (public.is_class_teacher(class_id));

create policy "class_members_admin_select" on public.class_members
  for select to authenticated
  using (public.is_admin());

-- A student inserts ONLY their own row, and it must land 'pending'.
create policy "class_members_student_insert" on public.class_members
  for insert to authenticated
  with check (student_id = auth.uid() and status = 'pending');

-- Only the class's teacher may update a membership (e.g. flip to 'active').
create policy "class_members_teacher_update" on public.class_members
  for update to authenticated
  using (public.is_class_teacher(class_id))
  with check (public.is_class_teacher(class_id));

-- The class's teacher may remove a student.
create policy "class_members_teacher_delete" on public.class_members
  for delete to authenticated
  using (public.is_class_teacher(class_id));

-- A student may withdraw their own membership.
create policy "class_members_student_delete" on public.class_members
  for delete to authenticated
  using (student_id = auth.uid());

-- ── class_courses ──────────────────────────────────────────────────────────
alter table public.class_courses enable row level security;

drop policy if exists "class_courses_teacher_select" on public.class_courses;
drop policy if exists "class_courses_member_select"  on public.class_courses;
drop policy if exists "class_courses_admin_select"   on public.class_courses;
drop policy if exists "class_courses_teacher_insert" on public.class_courses;
drop policy if exists "class_courses_teacher_delete" on public.class_courses;

-- The class's teacher (reached via class_id -> classes.teacher_id), and an
-- active member of the class — both routed through definer helpers so they do
-- not recurse into classes / class_members RLS.
create policy "class_courses_teacher_select" on public.class_courses
  for select to authenticated
  using (public.is_class_teacher(class_id));

create policy "class_courses_member_select" on public.class_courses
  for select to authenticated
  using (public.is_active_class_member(class_id));

create policy "class_courses_admin_select" on public.class_courses
  for select to authenticated
  using (public.is_admin());

create policy "class_courses_teacher_insert" on public.class_courses
  for insert to authenticated
  with check (public.is_class_teacher(class_id));

create policy "class_courses_teacher_delete" on public.class_courses
  for delete to authenticated
  using (public.is_class_teacher(class_id));

-- ── lesson_materials ───────────────────────────────────────────────────────
alter table public.lesson_materials enable row level security;

drop policy if exists "lesson_materials_owner_select" on public.lesson_materials;
drop policy if exists "lesson_materials_admin_select" on public.lesson_materials;
drop policy if exists "lesson_materials_owner_insert" on public.lesson_materials;
drop policy if exists "lesson_materials_owner_update" on public.lesson_materials;
drop policy if exists "lesson_materials_owner_delete" on public.lesson_materials;

create policy "lesson_materials_owner_select" on public.lesson_materials
  for select to authenticated
  using (public.is_unit_owner(unit_id));

create policy "lesson_materials_admin_select" on public.lesson_materials
  for select to authenticated
  using (public.is_admin());

create policy "lesson_materials_owner_insert" on public.lesson_materials
  for insert to authenticated
  with check (public.is_unit_owner(unit_id));

create policy "lesson_materials_owner_update" on public.lesson_materials
  for update to authenticated
  using (public.is_unit_owner(unit_id))
  with check (public.is_unit_owner(unit_id));

create policy "lesson_materials_owner_delete" on public.lesson_materials
  for delete to authenticated
  using (public.is_unit_owner(unit_id));

-- ── material_pages ─────────────────────────────────────────────────────────
-- Reaches the teacher through material_id -> lesson_materials.unit_id.
alter table public.material_pages enable row level security;

drop policy if exists "material_pages_owner_select" on public.material_pages;
drop policy if exists "material_pages_admin_select" on public.material_pages;
drop policy if exists "material_pages_owner_insert" on public.material_pages;
drop policy if exists "material_pages_owner_update" on public.material_pages;
drop policy if exists "material_pages_owner_delete" on public.material_pages;

create policy "material_pages_owner_select" on public.material_pages
  for select to authenticated
  using (
    exists (
      select 1 from public.lesson_materials m
      where m.id = material_pages.material_id
        and public.is_unit_owner(m.unit_id)
    )
  );

create policy "material_pages_admin_select" on public.material_pages
  for select to authenticated
  using (public.is_admin());

create policy "material_pages_owner_insert" on public.material_pages
  for insert to authenticated
  with check (
    exists (
      select 1 from public.lesson_materials m
      where m.id = material_pages.material_id
        and public.is_unit_owner(m.unit_id)
    )
  );

create policy "material_pages_owner_update" on public.material_pages
  for update to authenticated
  using (
    exists (
      select 1 from public.lesson_materials m
      where m.id = material_pages.material_id
        and public.is_unit_owner(m.unit_id)
    )
  )
  with check (
    exists (
      select 1 from public.lesson_materials m
      where m.id = material_pages.material_id
        and public.is_unit_owner(m.unit_id)
    )
  );

create policy "material_pages_owner_delete" on public.material_pages
  for delete to authenticated
  using (
    exists (
      select 1 from public.lesson_materials m
      where m.id = material_pages.material_id
        and public.is_unit_owner(m.unit_id)
    )
  );

-- ── unit_segmentations ─────────────────────────────────────────────────────
alter table public.unit_segmentations enable row level security;

drop policy if exists "unit_segmentations_owner_select" on public.unit_segmentations;
drop policy if exists "unit_segmentations_admin_select" on public.unit_segmentations;
drop policy if exists "unit_segmentations_owner_insert" on public.unit_segmentations;
drop policy if exists "unit_segmentations_owner_update" on public.unit_segmentations;
drop policy if exists "unit_segmentations_owner_delete" on public.unit_segmentations;

create policy "unit_segmentations_owner_select" on public.unit_segmentations
  for select to authenticated
  using (public.is_unit_owner(unit_id));

create policy "unit_segmentations_admin_select" on public.unit_segmentations
  for select to authenticated
  using (public.is_admin());

create policy "unit_segmentations_owner_insert" on public.unit_segmentations
  for insert to authenticated
  with check (public.is_unit_owner(unit_id));

create policy "unit_segmentations_owner_update" on public.unit_segmentations
  for update to authenticated
  using (public.is_unit_owner(unit_id))
  with check (public.is_unit_owner(unit_id));

create policy "unit_segmentations_owner_delete" on public.unit_segmentations
  for delete to authenticated
  using (public.is_unit_owner(unit_id));

-- ── topic_pages ────────────────────────────────────────────────────────────
-- Reaches the teacher through topic_id -> topics -> units -> courses.owner_id.
alter table public.topic_pages enable row level security;

drop policy if exists "topic_pages_owner_select"  on public.topic_pages;
drop policy if exists "topic_pages_member_select" on public.topic_pages;
drop policy if exists "topic_pages_admin_select"  on public.topic_pages;
drop policy if exists "topic_pages_owner_insert"  on public.topic_pages;
drop policy if exists "topic_pages_owner_update"  on public.topic_pages;
drop policy if exists "topic_pages_owner_delete"  on public.topic_pages;

create policy "topic_pages_owner_select" on public.topic_pages
  for select to authenticated
  using (public.is_topic_owner(topic_id));

-- A student on a published topic they can read needs its page set so the
-- classroom can render slide-backed steps.
create policy "topic_pages_member_select" on public.topic_pages
  for select to authenticated
  using (
    exists (
      select 1
      from public.topics t
      join public.units u on u.id = t.unit_id
      join public.courses c on c.id = u.course_id
      where t.id = topic_pages.topic_id
        and t.status = 'published'
        and c.origin = 'teacher'
        and public.is_active_member_of_course(c.id)
    )
  );

create policy "topic_pages_admin_select" on public.topic_pages
  for select to authenticated
  using (public.is_admin());

create policy "topic_pages_owner_insert" on public.topic_pages
  for insert to authenticated
  with check (public.is_topic_owner(topic_id));

create policy "topic_pages_owner_update" on public.topic_pages
  for update to authenticated
  using (public.is_topic_owner(topic_id))
  with check (public.is_topic_owner(topic_id));

create policy "topic_pages_owner_delete" on public.topic_pages
  for delete to authenticated
  using (public.is_topic_owner(topic_id));

-- ── topic_versions ─────────────────────────────────────────────────────────
alter table public.topic_versions enable row level security;

drop policy if exists "topic_versions_owner_select" on public.topic_versions;
drop policy if exists "topic_versions_admin_select" on public.topic_versions;
drop policy if exists "topic_versions_owner_insert" on public.topic_versions;
drop policy if exists "topic_versions_owner_update" on public.topic_versions;
drop policy if exists "topic_versions_owner_delete" on public.topic_versions;

create policy "topic_versions_owner_select" on public.topic_versions
  for select to authenticated
  using (public.is_topic_owner(topic_id));

create policy "topic_versions_admin_select" on public.topic_versions
  for select to authenticated
  using (public.is_admin());

create policy "topic_versions_owner_insert" on public.topic_versions
  for insert to authenticated
  with check (public.is_topic_owner(topic_id));

create policy "topic_versions_owner_update" on public.topic_versions
  for update to authenticated
  using (public.is_topic_owner(topic_id))
  with check (public.is_topic_owner(topic_id));

create policy "topic_versions_owner_delete" on public.topic_versions
  for delete to authenticated
  using (public.is_topic_owner(topic_id));

-- ── pipeline_jobs ──────────────────────────────────────────────────────────
-- A 'segment' job carries unit_id; a 'generate' job carries topic_id. A row is
-- owned by the teacher who owns whichever of those it references.
alter table public.pipeline_jobs enable row level security;

drop policy if exists "pipeline_jobs_owner_select" on public.pipeline_jobs;
drop policy if exists "pipeline_jobs_admin_select" on public.pipeline_jobs;
drop policy if exists "pipeline_jobs_owner_insert" on public.pipeline_jobs;
drop policy if exists "pipeline_jobs_owner_update" on public.pipeline_jobs;
drop policy if exists "pipeline_jobs_owner_delete" on public.pipeline_jobs;

create policy "pipeline_jobs_owner_select" on public.pipeline_jobs
  for select to authenticated
  using (
    (unit_id is not null and public.is_unit_owner(unit_id))
    or (topic_id is not null and public.is_topic_owner(topic_id))
  );

create policy "pipeline_jobs_admin_select" on public.pipeline_jobs
  for select to authenticated
  using (public.is_admin());

create policy "pipeline_jobs_owner_insert" on public.pipeline_jobs
  for insert to authenticated
  with check (
    (unit_id is not null and public.is_unit_owner(unit_id))
    or (topic_id is not null and public.is_topic_owner(topic_id))
  );

create policy "pipeline_jobs_owner_update" on public.pipeline_jobs
  for update to authenticated
  using (
    (unit_id is not null and public.is_unit_owner(unit_id))
    or (topic_id is not null and public.is_topic_owner(topic_id))
  )
  with check (
    (unit_id is not null and public.is_unit_owner(unit_id))
    or (topic_id is not null and public.is_topic_owner(topic_id))
  );

create policy "pipeline_jobs_owner_delete" on public.pipeline_jobs
  for delete to authenticated
  using (
    (unit_id is not null and public.is_unit_owner(unit_id))
    or (topic_id is not null and public.is_topic_owner(topic_id))
  );

-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ PART F — HARDEN THE RLS HELPER FUNCTIONS                                  ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
-- The PART C helpers are SECURITY DEFINER — they must read the curriculum
-- tree past RLS, which is the whole point. But that also makes them callable
-- via PostgREST `/rest/v1/rpc/...`. They are internal RLS plumbing, not a
-- public API, so EXECUTE is revoked from PUBLIC + anon. `authenticated` keeps
-- it because the PART D/E policies invoke these functions inside an
-- authenticated user's own query; `service_role` keeps it for the API.
-- (Each helper is scoped to auth.uid() and returns only a boolean, so even
-- the prior exposure leaked nothing — this is defense-in-depth.)
-- Idempotent: revoke/grant are naturally re-runnable.
do $$
declare fn text;
begin
  foreach fn in array array[
    'public.is_unit_owner(uuid)','public.is_topic_owner(uuid)',
    'public.is_active_member_of_course(uuid)','public.is_admin()',
    'public.is_class_teacher(uuid)','public.is_class_member(uuid)',
    'public.is_active_class_member(uuid)'
  ] loop
    execute format('revoke execute on function %s from public, anon', fn);
    execute format('grant execute on function %s to authenticated, service_role', fn);
  end loop;
end $$;

-- ============================================================================
-- End of migration.
-- ============================================================================
