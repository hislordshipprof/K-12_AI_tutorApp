-- ============================================================================
-- Q1: quiz_questions — per-topic multiple-choice question bank.
--
-- Until now /v1/quiz/{topic_id} returned one hardcoded sample question for
-- every topic. With the content pipeline grounded in OpenStax chunks, we can
-- now generate real, topic-specific questions and persist them here.
--
-- One question per row; `(topic_id, idx)` is the natural key the API uses
-- when scoring an attempt — quiz_attempts.question_idx already stores `idx`,
-- so this table joins to attempts without a schema change.
-- ============================================================================

create table if not exists public.quiz_questions (
  id           uuid primary key default gen_random_uuid(),
  topic_id     uuid not null references public.topics(id) on delete cascade,
  idx          int  not null,
  prompt       text not null,
  choices      jsonb not null,
  correct_idx  int  not null check (correct_idx between 0 and 3),
  explanation  text not null,
  provenance   jsonb,
  created_at   timestamptz not null default now(),
  unique (topic_id, idx)
);

create index if not exists quiz_questions_topic_idx on public.quiz_questions (topic_id);

-- Sanity: choices must be a 4-element JSON array of non-empty strings.
-- We enforce length at the app layer (Pydantic) and via a CHECK below so a
-- bad row can't slip in via raw SQL either.
alter table public.quiz_questions
  drop constraint if exists quiz_questions_choices_shape;
alter table public.quiz_questions
  add constraint quiz_questions_choices_shape
  check (
    jsonb_typeof(choices) = 'array'
    and jsonb_array_length(choices) = 4
  );

-- RLS: same pattern as topics — readable by any authenticated user, no
-- public writes. Writes happen via service-role from the content CLI.
alter table public.quiz_questions enable row level security;

drop policy if exists "quiz_questions_read_all" on public.quiz_questions;
create policy "quiz_questions_read_all" on public.quiz_questions
  for select to authenticated using (true);
