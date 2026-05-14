-- ============================================================================
-- K-12 AI Tutor — Base Schema
-- ----------------------------------------------------------------------------
-- Creates all tables, extensions, and indexes for the tutoring app.
-- RLS policies and helper functions live in subsequent migrations.
-- ============================================================================

-- Extensions ----------------------------------------------------------------
create extension if not exists "pgcrypto";   -- gen_random_uuid()
create extension if not exists "vector";     -- pgvector for lesson_embeddings

-- ============================================================================
-- profiles  (1-1 with auth.users)
-- ============================================================================
create table if not exists public.profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  full_name     text,
  grade         text,
  goal          text,
  streak_days   int default 0,
  last_active   timestamptz,
  avatar_color  text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- ============================================================================
-- courses / units / topics  (curriculum tree, public-readable)
-- ============================================================================
create table if not exists public.courses (
  id              uuid primary key default gen_random_uuid(),
  slug            text unique not null,
  title           text not null,
  exam            text,
  color_gradient  text,
  icon_emoji      text,
  sort_order      int default 0,
  created_at      timestamptz not null default now()
);

create table if not exists public.units (
  id          uuid primary key default gen_random_uuid(),
  course_id   uuid not null references public.courses(id) on delete cascade,
  n           int not null,
  name        text not null,
  sort_order  int default 0,
  created_at  timestamptz not null default now(),
  unique (course_id, n)
);

create table if not exists public.topics (
  id            uuid primary key default gen_random_uuid(),
  unit_id       uuid not null references public.units(id) on delete cascade,
  n             int not null,
  name          text not null,
  duration_min  int,
  summary       text,
  content       jsonb,           -- [{tts, html, dur}, ...] lesson steps
  sort_order    int default 0,
  created_at    timestamptz not null default now(),
  unique (unit_id, n)
);

create index if not exists idx_units_course   on public.units(course_id);
create index if not exists idx_topics_unit    on public.topics(unit_id);

-- ============================================================================
-- enrollments  (user <> course)
-- ============================================================================
create table if not exists public.enrollments (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.profiles(id) on delete cascade,
  course_id     uuid not null references public.courses(id) on delete cascade,
  started_at    timestamptz not null default now(),
  target_score  text,
  created_at    timestamptz not null default now(),
  unique (user_id, course_id)
);

create index if not exists idx_enrollments_user    on public.enrollments(user_id);
create index if not exists idx_enrollments_course  on public.enrollments(course_id);

-- ============================================================================
-- topic_progress  (per-user, per-topic state)
-- ============================================================================
create table if not exists public.topic_progress (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.profiles(id) on delete cascade,
  topic_id       uuid not null references public.topics(id) on delete cascade,
  status         text not null default 'not_started'
                 check (status in ('not_started','in_progress','done')),
  score          int,
  time_spent_s   int default 0,
  last_step_idx  int default 0,
  completed_at   timestamptz,
  updated_at     timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  unique (user_id, topic_id)
);

create index if not exists idx_topic_progress_user   on public.topic_progress(user_id);
create index if not exists idx_topic_progress_topic  on public.topic_progress(topic_id);

-- ============================================================================
-- lesson_sessions  (one "Aria teaches a topic" session)
-- ============================================================================
create table if not exists public.lesson_sessions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.profiles(id) on delete cascade,
  topic_id     uuid not null references public.topics(id) on delete cascade,
  started_at   timestamptz not null default now(),
  ended_at     timestamptz,
  agent_state  jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);

create index if not exists idx_lesson_sessions_user   on public.lesson_sessions(user_id);
create index if not exists idx_lesson_sessions_topic  on public.lesson_sessions(topic_id);

-- ============================================================================
-- qa_questions  (Q&A panel — text/voice/sketch-originated questions)
-- ============================================================================
create table if not exists public.qa_questions (
  id           uuid primary key default gen_random_uuid(),
  session_id   uuid not null references public.lesson_sessions(id) on delete cascade,
  q_text       text not null,
  q_audio_url  text,
  a_text       text,
  a_topic      text,
  source       text not null check (source in ('text','voice','sketch')),
  created_at   timestamptz not null default now()
);

create index if not exists idx_qa_questions_session on public.qa_questions(session_id);

-- ============================================================================
-- sketches  (chalkboard SVG strokes + AI recognition)
-- ============================================================================
create table if not exists public.sketches (
  id                uuid primary key default gen_random_uuid(),
  session_id        uuid not null references public.lesson_sessions(id) on delete cascade,
  svg_data          text not null,
  png_data_url      text,
  recognized_shape  text,
  ai_response       text,
  created_at        timestamptz not null default now()
);

create index if not exists idx_sketches_session on public.sketches(session_id);

-- ============================================================================
-- quiz_attempts  (one row per question attempt)
-- ============================================================================
create table if not exists public.quiz_attempts (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.profiles(id) on delete cascade,
  topic_id      uuid not null references public.topics(id) on delete cascade,
  question_idx  int not null,
  picked_idx    int,
  correct       boolean,
  created_at    timestamptz not null default now()
);

create index if not exists idx_quiz_attempts_user   on public.quiz_attempts(user_id);
create index if not exists idx_quiz_attempts_topic  on public.quiz_attempts(topic_id);

-- ============================================================================
-- notes  (auto-generated, user-saved, or Aria-suggested notes)
-- ============================================================================
create table if not exists public.notes (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references public.profiles(id) on delete cascade,
  topic_id           uuid references public.topics(id) on delete set null,
  kind               text not null check (kind in ('auto','user','qa','aria')),
  title              text,
  body               text,
  color              text,
  pinned             boolean not null default false,
  source_session_id  uuid references public.lesson_sessions(id) on delete set null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists idx_notes_user   on public.notes(user_id);
create index if not exists idx_notes_topic  on public.notes(topic_id);

-- ============================================================================
-- decks + flashcards  (SM-2 spaced repetition)
-- ============================================================================
create table if not exists public.decks (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.profiles(id) on delete cascade,
  name        text not null,
  topic_ids   uuid[] not null default '{}',
  created_at  timestamptz not null default now()
);

create index if not exists idx_decks_user on public.decks(user_id);

create table if not exists public.flashcards (
  id                uuid primary key default gen_random_uuid(),
  deck_id           uuid not null references public.decks(id) on delete cascade,
  user_id           uuid not null references public.profiles(id) on delete cascade,
  front             text not null,
  back              text not null,
  ease              real not null default 2.5,
  interval_days     int not null default 1,
  due_at            date not null default current_date,
  last_reviewed_at  timestamptz,
  created_at        timestamptz not null default now()
);

create index if not exists idx_flashcards_deck         on public.flashcards(deck_id);
create index if not exists idx_flashcards_user_due     on public.flashcards(user_id, due_at);

-- ============================================================================
-- schedule_blocks  (study plan calendar entries)
-- ============================================================================
create table if not exists public.schedule_blocks (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.profiles(id) on delete cascade,
  date          date not null,
  start_time    time,
  duration_min  int,
  kind          text not null check (kind in ('lesson','quiz','flashcards','office_hours','rest')),
  payload       jsonb not null default '{}'::jsonb,
  status        text not null default 'planned' check (status in ('planned','done','skipped')),
  created_at    timestamptz not null default now()
);

create index if not exists idx_schedule_blocks_user_date on public.schedule_blocks(user_id, date);

-- ============================================================================
-- agent_traces  (observability — service_role only)
-- ============================================================================
create table if not exists public.agent_traces (
  id          uuid primary key default gen_random_uuid(),
  session_id  uuid references public.lesson_sessions(id) on delete set null,
  user_id     uuid references public.profiles(id) on delete set null,
  step        text,
  agent       text,
  input       jsonb,
  output      jsonb,
  latency_ms  int,
  created_at  timestamptz not null default now()
);

create index if not exists idx_agent_traces_session on public.agent_traces(session_id);
create index if not exists idx_agent_traces_user    on public.agent_traces(user_id);

-- ============================================================================
-- lesson_embeddings  (pgvector — public-readable, semantic lookup)
-- ============================================================================
create table if not exists public.lesson_embeddings (
  topic_id    uuid primary key references public.topics(id) on delete cascade,
  embedding   vector(768),
  summary     text,
  created_at  timestamptz not null default now()
);
