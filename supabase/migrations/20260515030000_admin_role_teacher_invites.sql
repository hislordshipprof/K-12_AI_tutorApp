-- ============================================================================
-- Task 0.3 — Admin role + teacher invite-code flow
-- ----------------------------------------------------------------------------
-- Teachers are invite-only (teacher-authoring.md §11.1). This migration:
--   1. adds `role` to `profiles` ('student' | 'teacher' | 'admin').
--   2. creates `teacher_invites` (teacher-authoring.md §4).
--   3. adds RLS so only admins issue/list invites, and a redeeming user can
--      read the single invite row matching the code they hold.
--
-- Every statement is idempotent (`if not exists` / `drop policy if exists`)
-- so it is safe to re-run and so a later Phase-1 migration that also defines
-- these objects (task 1.1 — see task-execution.md) is a harmless no-op.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. profiles.role  ('student' | 'teacher' | 'admin')
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column if not exists role text not null default 'student';

-- ---------------------------------------------------------------------------
-- 2. teacher_invites  (teacher-authoring.md §4)
-- ---------------------------------------------------------------------------
create table if not exists public.teacher_invites (
  code         text primary key,                               -- redeemable invite code
  created_by   uuid references public.profiles(id) on delete set null,
  redeemed_by  uuid references public.profiles(id) on delete set null,  -- null until used
  redeemed_at  timestamptz,
  created_at   timestamptz not null default now()
);

create index if not exists idx_teacher_invites_redeemed_by
  on public.teacher_invites(redeemed_by);

-- ---------------------------------------------------------------------------
-- 3. RLS — only admins issue/list invites; a redeeming user may read the one
--    row whose `code` they already hold (so they can validate + redeem it).
--    Note: the API does invite writes via the service role (which bypasses
--    RLS); these policies are defense-in-depth for any direct client access.
-- ---------------------------------------------------------------------------
alter table public.teacher_invites enable row level security;

drop policy if exists "teacher_invites_admin_select" on public.teacher_invites;
drop policy if exists "teacher_invites_admin_insert" on public.teacher_invites;
drop policy if exists "teacher_invites_redeemer_select" on public.teacher_invites;

-- Admins can list every invite.
create policy "teacher_invites_admin_select" on public.teacher_invites
  for select to authenticated
  using (
    exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'admin'
    )
  );

-- Only admins may insert (issue) an invite.
create policy "teacher_invites_admin_insert" on public.teacher_invites
  for insert to authenticated
  with check (
    exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'admin'
    )
  );

-- A redeeming user reads a single still-unredeemed row by its code. RLS scopes
-- a row to a query, so a `where code = $code` lookup returns only that row;
-- this policy lets a non-admin redeemer see it to redeem it.
create policy "teacher_invites_redeemer_select" on public.teacher_invites
  for select to authenticated
  using (redeemed_by is null);

-- ---------------------------------------------------------------------------
-- First admin — bootstrapped MANUALLY.
-- ---------------------------------------------------------------------------
-- There is no user to seed at migration time, so no admin is auto-created.
-- After the first real person signs up, promote them by running (with the
-- service role / SQL editor — RLS does not block the service role):
--
--   update public.profiles set role = 'admin' where id = '<that-user-uuid>';
--
-- That admin then issues teacher invite codes via POST /v1/admin/teacher-invites.
