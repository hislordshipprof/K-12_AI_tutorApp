-- ============================================================================
-- Task 5.2 — Course cover art
-- ----------------------------------------------------------------------------
-- model-strategy.md §4: teacher courses need visual identity. A cover image
-- is generated once per course (Nano Banana 2) at publish time and cached.
--
-- This migration adds:
--   1. `courses.cover_image_path` — the object key of the generated cover in
--      the `course-covers` bucket; NULL until a cover has been generated
--      (the dashboard then falls back to the gradient).
--   2. A PUBLIC `course-covers` Storage bucket — covers are cosmetic and
--      non-sensitive, so a public bucket gives a stable, cacheable URL with
--      no per-request signing. The pipeline writes via the service role
--      (which bypasses RLS); everyone reads.
--
-- Idempotent: `add column if not exists`, `on conflict do nothing` for the
-- bucket, `drop policy if exists` before the policy.
-- ============================================================================

alter table courses add column if not exists cover_image_path text;

insert into storage.buckets (id, name, public)
values ('course-covers', 'course-covers', true)
on conflict (id) do nothing;

-- Public read on the bucket's objects — covers are non-sensitive and served
-- straight to the student dashboard. Writes are service-role only (the cover
-- pipeline), so no insert/update/delete policy is granted to end users.
drop policy if exists "course_covers_public_read" on storage.objects;

create policy "course_covers_public_read" on storage.objects
  for select to public
  using (bucket_id = 'course-covers');

-- ============================================================================
-- End of migration.
-- ============================================================================
