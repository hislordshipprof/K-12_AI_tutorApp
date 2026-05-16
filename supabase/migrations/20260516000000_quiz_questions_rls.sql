-- ============================================================================
-- Task 2.6 — quiz_questions RLS: split recommended-vs-teacher reads.
-- ----------------------------------------------------------------------------
-- Carry-over from task 1.2 (noted in docs/task-execution.md §1.2): the
-- original `quiz_questions` table (migration 20260515000000) shipped a
-- world-readable policy `quiz_questions_read_all` — readable by ANY
-- authenticated user. That was harmless while only Recommended (OpenStax)
-- courses had quizzes, but task 2.6 makes teacher courses generate
-- version-scoped quizzes, and a teacher's quiz for an UNPUBLISHED topic, or
-- a topic of a course no class the caller belongs to is assigned, must NOT
-- leak.
--
-- The replacement mirrors the `topics_read_recommended` / `topics_read_teacher`
-- policy pair from 20260515050000:
--   * Recommended-course questions (topic -> unit -> course origin =
--     'recommended') stay world-readable to `authenticated` — unchanged
--     behaviour for the built-in AP courses.
--   * Teacher-course questions follow the topic-visibility rule: the
--     owner-teacher and an admin see ALL of a teacher course's questions; an
--     active-member student sees a question ONLY for a 'published' topic of
--     a course assigned to a class they are an ACTIVE member of.
--
-- A `quiz_questions` row reaches its topic via `quiz_questions.topic_id`,
-- then the topic rolls up topic -> unit -> course exactly as the topics
-- policies do. The existing SECURITY DEFINER helpers `is_active_member_of_course`
-- and `is_admin` (from 20260515050000) are reused — no new helper is needed.
--
-- quiz_questions writes still happen via the service role, which bypasses
-- RLS; there is no `for insert/update/delete` policy here (none existed
-- before either — the content pipeline and task 2.6's `generate_quiz` both
-- use the service-role client).
--
-- Idempotent: `drop policy if exists` precedes every `create policy`, and
-- RLS-enable is naturally re-runnable. Safe to re-apply.
-- ============================================================================

alter table public.quiz_questions enable row level security;

-- Drop the legacy world-read policy and any prior cut of the split policies.
drop policy if exists "quiz_questions_read_all"         on public.quiz_questions;
drop policy if exists "quiz_questions_read_recommended" on public.quiz_questions;
drop policy if exists "quiz_questions_read_teacher"     on public.quiz_questions;

-- Recommended-course questions: world-readable to any authenticated user
-- (the built-in AP courses — unchanged from `quiz_questions_read_all`, just
-- now scoped to origin='recommended').
create policy "quiz_questions_read_recommended" on public.quiz_questions
  for select to authenticated
  using (
    exists (
      select 1
      from public.topics t
      join public.units u on u.id = t.unit_id
      join public.courses c on c.id = u.course_id
      where t.id = quiz_questions.topic_id
        and c.origin = 'recommended'
    )
  );

-- Teacher-course questions: the owner-teacher and an admin see all; an
-- active-member student sees questions ONLY for a 'published' topic of an
-- assigned course. Mirrors `topics_read_teacher`.
create policy "quiz_questions_read_teacher" on public.quiz_questions
  for select to authenticated
  using (
    exists (
      select 1
      from public.topics t
      join public.units u on u.id = t.unit_id
      join public.courses c on c.id = u.course_id
      where t.id = quiz_questions.topic_id
        and c.origin = 'teacher'
        and (
          c.owner_id = auth.uid()
          or public.is_admin()
          or (
            t.status = 'published'
            and public.is_active_member_of_course(c.id)
          )
        )
    )
  );

-- ============================================================================
-- End of migration.
-- ============================================================================
