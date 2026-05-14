-- ============================================================================
-- K-12 AI Tutor — Row-Level Security
-- ----------------------------------------------------------------------------
-- Pattern: enable RLS on every table, then add explicit policies.
--   - public-read tables  : curriculum (courses, units, topics, lesson_embeddings)
--   - owner-only tables   : all user-owned data (auth.uid() = user_id)
--   - join-scoped tables  : qa_questions / sketches (via lesson_sessions)
--   - service_role only   : agent_traces
-- ============================================================================

-- ---------------------------------------------------------------------------
-- profiles
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;

drop policy if exists "profiles_select_own"  on public.profiles;
drop policy if exists "profiles_insert_self" on public.profiles;
drop policy if exists "profiles_update_own"  on public.profiles;

create policy "profiles_select_own"
  on public.profiles for select
  using (auth.uid() = id);

create policy "profiles_insert_self"
  on public.profiles for insert
  with check (auth.uid() = id);

create policy "profiles_update_own"
  on public.profiles for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- ---------------------------------------------------------------------------
-- courses / units / topics  (public read, no public write)
-- ---------------------------------------------------------------------------
alter table public.courses enable row level security;
alter table public.units   enable row level security;
alter table public.topics  enable row level security;

drop policy if exists "courses_read_all" on public.courses;
drop policy if exists "units_read_all"   on public.units;
drop policy if exists "topics_read_all"  on public.topics;

create policy "courses_read_all" on public.courses
  for select to authenticated using (true);

create policy "units_read_all" on public.units
  for select to authenticated using (true);

create policy "topics_read_all" on public.topics
  for select to authenticated using (true);

-- ---------------------------------------------------------------------------
-- lesson_embeddings  (public read, no public write)
-- ---------------------------------------------------------------------------
alter table public.lesson_embeddings enable row level security;

drop policy if exists "lesson_embeddings_read_all" on public.lesson_embeddings;

create policy "lesson_embeddings_read_all" on public.lesson_embeddings
  for select to authenticated using (true);

-- ---------------------------------------------------------------------------
-- enrollments
-- ---------------------------------------------------------------------------
alter table public.enrollments enable row level security;

drop policy if exists "enrollments_select_own" on public.enrollments;
drop policy if exists "enrollments_insert_own" on public.enrollments;
drop policy if exists "enrollments_update_own" on public.enrollments;
drop policy if exists "enrollments_delete_own" on public.enrollments;

create policy "enrollments_select_own" on public.enrollments
  for select using (auth.uid() = user_id);
create policy "enrollments_insert_own" on public.enrollments
  for insert with check (auth.uid() = user_id);
create policy "enrollments_update_own" on public.enrollments
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "enrollments_delete_own" on public.enrollments
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- topic_progress
-- ---------------------------------------------------------------------------
alter table public.topic_progress enable row level security;

drop policy if exists "topic_progress_select_own" on public.topic_progress;
drop policy if exists "topic_progress_insert_own" on public.topic_progress;
drop policy if exists "topic_progress_update_own" on public.topic_progress;
drop policy if exists "topic_progress_delete_own" on public.topic_progress;

create policy "topic_progress_select_own" on public.topic_progress
  for select using (auth.uid() = user_id);
create policy "topic_progress_insert_own" on public.topic_progress
  for insert with check (auth.uid() = user_id);
create policy "topic_progress_update_own" on public.topic_progress
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "topic_progress_delete_own" on public.topic_progress
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- lesson_sessions
-- ---------------------------------------------------------------------------
alter table public.lesson_sessions enable row level security;

drop policy if exists "lesson_sessions_select_own" on public.lesson_sessions;
drop policy if exists "lesson_sessions_insert_own" on public.lesson_sessions;
drop policy if exists "lesson_sessions_update_own" on public.lesson_sessions;
drop policy if exists "lesson_sessions_delete_own" on public.lesson_sessions;

create policy "lesson_sessions_select_own" on public.lesson_sessions
  for select using (auth.uid() = user_id);
create policy "lesson_sessions_insert_own" on public.lesson_sessions
  for insert with check (auth.uid() = user_id);
create policy "lesson_sessions_update_own" on public.lesson_sessions
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "lesson_sessions_delete_own" on public.lesson_sessions
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- qa_questions  (scoped via session)
-- ---------------------------------------------------------------------------
alter table public.qa_questions enable row level security;

drop policy if exists "qa_questions_select_via_session" on public.qa_questions;
drop policy if exists "qa_questions_insert_via_session" on public.qa_questions;
drop policy if exists "qa_questions_update_via_session" on public.qa_questions;
drop policy if exists "qa_questions_delete_via_session" on public.qa_questions;

create policy "qa_questions_select_via_session" on public.qa_questions
  for select using (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = qa_questions.session_id and s.user_id = auth.uid()
    )
  );
create policy "qa_questions_insert_via_session" on public.qa_questions
  for insert with check (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = qa_questions.session_id and s.user_id = auth.uid()
    )
  );
create policy "qa_questions_update_via_session" on public.qa_questions
  for update using (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = qa_questions.session_id and s.user_id = auth.uid()
    )
  ) with check (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = qa_questions.session_id and s.user_id = auth.uid()
    )
  );
create policy "qa_questions_delete_via_session" on public.qa_questions
  for delete using (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = qa_questions.session_id and s.user_id = auth.uid()
    )
  );

-- ---------------------------------------------------------------------------
-- sketches  (scoped via session)
-- ---------------------------------------------------------------------------
alter table public.sketches enable row level security;

drop policy if exists "sketches_select_via_session" on public.sketches;
drop policy if exists "sketches_insert_via_session" on public.sketches;
drop policy if exists "sketches_update_via_session" on public.sketches;
drop policy if exists "sketches_delete_via_session" on public.sketches;

create policy "sketches_select_via_session" on public.sketches
  for select using (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = sketches.session_id and s.user_id = auth.uid()
    )
  );
create policy "sketches_insert_via_session" on public.sketches
  for insert with check (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = sketches.session_id and s.user_id = auth.uid()
    )
  );
create policy "sketches_update_via_session" on public.sketches
  for update using (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = sketches.session_id and s.user_id = auth.uid()
    )
  ) with check (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = sketches.session_id and s.user_id = auth.uid()
    )
  );
create policy "sketches_delete_via_session" on public.sketches
  for delete using (
    exists (
      select 1 from public.lesson_sessions s
      where s.id = sketches.session_id and s.user_id = auth.uid()
    )
  );

-- ---------------------------------------------------------------------------
-- quiz_attempts
-- ---------------------------------------------------------------------------
alter table public.quiz_attempts enable row level security;

drop policy if exists "quiz_attempts_select_own" on public.quiz_attempts;
drop policy if exists "quiz_attempts_insert_own" on public.quiz_attempts;
drop policy if exists "quiz_attempts_update_own" on public.quiz_attempts;
drop policy if exists "quiz_attempts_delete_own" on public.quiz_attempts;

create policy "quiz_attempts_select_own" on public.quiz_attempts
  for select using (auth.uid() = user_id);
create policy "quiz_attempts_insert_own" on public.quiz_attempts
  for insert with check (auth.uid() = user_id);
create policy "quiz_attempts_update_own" on public.quiz_attempts
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "quiz_attempts_delete_own" on public.quiz_attempts
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- notes
-- ---------------------------------------------------------------------------
alter table public.notes enable row level security;

drop policy if exists "notes_select_own" on public.notes;
drop policy if exists "notes_insert_own" on public.notes;
drop policy if exists "notes_update_own" on public.notes;
drop policy if exists "notes_delete_own" on public.notes;

create policy "notes_select_own" on public.notes
  for select using (auth.uid() = user_id);
create policy "notes_insert_own" on public.notes
  for insert with check (auth.uid() = user_id);
create policy "notes_update_own" on public.notes
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "notes_delete_own" on public.notes
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- decks
-- ---------------------------------------------------------------------------
alter table public.decks enable row level security;

drop policy if exists "decks_select_own" on public.decks;
drop policy if exists "decks_insert_own" on public.decks;
drop policy if exists "decks_update_own" on public.decks;
drop policy if exists "decks_delete_own" on public.decks;

create policy "decks_select_own" on public.decks
  for select using (auth.uid() = user_id);
create policy "decks_insert_own" on public.decks
  for insert with check (auth.uid() = user_id);
create policy "decks_update_own" on public.decks
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "decks_delete_own" on public.decks
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- flashcards
-- ---------------------------------------------------------------------------
alter table public.flashcards enable row level security;

drop policy if exists "flashcards_select_own" on public.flashcards;
drop policy if exists "flashcards_insert_own" on public.flashcards;
drop policy if exists "flashcards_update_own" on public.flashcards;
drop policy if exists "flashcards_delete_own" on public.flashcards;

create policy "flashcards_select_own" on public.flashcards
  for select using (auth.uid() = user_id);
create policy "flashcards_insert_own" on public.flashcards
  for insert with check (auth.uid() = user_id);
create policy "flashcards_update_own" on public.flashcards
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "flashcards_delete_own" on public.flashcards
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- schedule_blocks
-- ---------------------------------------------------------------------------
alter table public.schedule_blocks enable row level security;

drop policy if exists "schedule_blocks_select_own" on public.schedule_blocks;
drop policy if exists "schedule_blocks_insert_own" on public.schedule_blocks;
drop policy if exists "schedule_blocks_update_own" on public.schedule_blocks;
drop policy if exists "schedule_blocks_delete_own" on public.schedule_blocks;

create policy "schedule_blocks_select_own" on public.schedule_blocks
  for select using (auth.uid() = user_id);
create policy "schedule_blocks_insert_own" on public.schedule_blocks
  for insert with check (auth.uid() = user_id);
create policy "schedule_blocks_update_own" on public.schedule_blocks
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "schedule_blocks_delete_own" on public.schedule_blocks
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- agent_traces  (service_role only — RLS on with no policies blocks all
-- access for authenticated/anon roles; service_role bypasses RLS by default)
-- ---------------------------------------------------------------------------
alter table public.agent_traces enable row level security;
-- (intentionally no policies — only service_role can read/write)
