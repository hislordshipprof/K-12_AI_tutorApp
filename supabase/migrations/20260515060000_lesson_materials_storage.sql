-- ============================================================================
-- Task 1.3 — `lesson-materials` Storage bucket + access rules
-- ----------------------------------------------------------------------------
-- teacher-authoring.md §10 "Storage": a private Supabase Storage bucket
-- `lesson-materials` holds the teacher's raw uploads AND the pipeline's
-- rendered slide PNGs. Access rules:
--   * Teachers write/read only their OWN prefix — the first path segment of
--     every object key is the uploading teacher's auth.uid(), e.g.
--     `lesson-materials/<teacher-uuid>/<unit>/<material>/<file>`.
--   * The pipeline reads via the service role, which bypasses RLS.
--   * Students NEVER touch the bucket directly — the classroom asks the API
--     for a short-lived signed URL (§10). They get no Storage policy here,
--     so RLS denies them by default.
--
-- The bucket is private (`public = false`); there is no anon/public read.
-- Idempotent: `on conflict do nothing` for the bucket, `drop policy if
-- exists` before each policy.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. The bucket — private.
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('lesson-materials', 'lesson-materials', false)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- 2. RLS on storage.objects — own-prefix only, scoped to this bucket.
-- ----------------------------------------------------------------------------
-- `storage.objects` already has RLS enabled (Supabase default). A teacher may
-- read/write an object only when it lives in `lesson-materials` AND its first
-- folder segment equals their own uid. Students own nothing here and cannot
-- read another prefix, so they have no bucket access at all. The service role
-- bypasses RLS, so the pipeline is unaffected.
-- ---------------------------------------------------------------------------
drop policy if exists "lesson_materials_own_prefix_select" on storage.objects;
drop policy if exists "lesson_materials_own_prefix_insert" on storage.objects;
drop policy if exists "lesson_materials_own_prefix_update" on storage.objects;
drop policy if exists "lesson_materials_own_prefix_delete" on storage.objects;

create policy "lesson_materials_own_prefix_select" on storage.objects
  for select to authenticated
  using (
    bucket_id = 'lesson-materials'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "lesson_materials_own_prefix_insert" on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'lesson-materials'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "lesson_materials_own_prefix_update" on storage.objects
  for update to authenticated
  using (
    bucket_id = 'lesson-materials'
    and (storage.foldername(name))[1] = auth.uid()::text
  )
  with check (
    bucket_id = 'lesson-materials'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "lesson_materials_own_prefix_delete" on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'lesson-materials'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- ============================================================================
-- End of migration.
-- ============================================================================
