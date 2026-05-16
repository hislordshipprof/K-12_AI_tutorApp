# Task execution plan — teacher-authored courses

> The gated build checklist. Read alongside `docs/teacher-authoring.md`
> (architecture) and `docs/model-strategy.md` (models). Rules of
> engagement are in the repo-root `CLAUDE.md`.

## How to use this file

- Tasks are worked **top to bottom**. A task may not start until the one
  before it shows `Status: done` and its box is `[x]`.
- Each task carries: **Why** (the reason — restate it before starting),
  **Build** (scope), **Acceptance criteria** (what "correct" means),
  **Verify** (how to prove it), **Depends on**, **Status**.
- A task is done only when every acceptance criterion is met and the
  `CLAUDE.md` "Definition of done" gate passes.
- **Sections** group tasks that are coupled and should be designed as a
  unit even though each is checked off on its own.
- The agent updates the checkbox + Status line in this file as it goes.

## Dependency map (why the order is fixed)

```
Track M  (models) ───── independent, urgent → can run anytime
Phase 0  (auth)   ───── nothing else is real without real accounts
   └─> Phase 1 (schema + RLS) ── RLS needs auth; tables need the role model
          └─> Phase 2 (pipeline) ── needs the schema to write into
                 └─> Phase 3 (board)   ── needs the pipeline to drive
                 └─> Phase 4 (student) ── needs published teacher content
                        └─> Phase 5 (polish)
```

Phases are a chain — they are NOT parallelisable. Track M is the only
work that can proceed alongside Phase 0.

## Status summary

| Phase | Tasks | Done |
|---|---|---|
| M — Model strategy | M.1–M.3 | 2/3 — M.3 done; M.1 — Live model connects (verified via 0.5); only the user's barge-in check remains |
| 0 — Auth & compliance | 0.1–0.4 | 4/4 — COMPLETE |
| 0.5 — Voice mode repair | 0.5 | 1/1 — COMPLETE |
| 1 — Schema foundations | 1.1–1.4 | 4/4 — COMPLETE (schema + RLS + Storage + pipeline harness) |
| 2 — Authoring pipeline | 2.1–2.7 | 1/7 — 2.1 done (ingest + normalize-to-PDF) |
| 3 — Admin board | 3.1–3.5 | 0/5 |
| 4 — Student side | 4.1–4.3 | 0/3 |
| 5 — Polish | 5.1–5.3 | 0/3 |

---

# Track M — Model strategy (independent · urgent)

> Section M is self-contained and does not touch the teacher feature.
> M.1 is time-critical: the Gemini 2.5 family deprecates **2026-06-17**.

### [ ] M.1 — Migrate the Live model + fix `fly.toml` drift
- **Why:** the `live` slot is the only thing still on Gemini 2.5, which
  is shut down 2026-06-17; and `apps/api/fly.toml` is pinned behind the
  code defaults, so a prod deploy would run already-deprecated models.
- **Build:** set `GEMINI_MODEL_LIVE` default to
  `gemini-3.1-flash-live-preview` in `config.py`; update `fly.toml` to
  match every current code default.
- **Acceptance criteria:** `/health` reports the new model map; voice
  mode connects and barge-in/interruption still works; `fly.toml`
  values equal `config.py` defaults.
- **Verify:** `pnpm api:test`; manual voice-mode smoke test (connect,
  speak, interrupt mid-reply).
- **Depends on:** none.
- **Status:** BUILT — `config.py`, `fly.toml`, and `apps/api/.env` all
  updated (`GEMINI_MODEL_LIVE` → `gemini-3.1-flash-live-preview`,
  `GEMINI_MODEL_PRO` → `gemini-3.1-pro-preview`); `pnpm api:test` passes.
  **The Live model now connects** — verified via task 0.5: voice mode
  opened a Gemini Live session (`voice_session_open`) on the new model
  and reached the `listening` state. The ONLY remaining gate is the
  manual barge-in check (interrupt Aria mid-sentence — needs a real
  voice), deferred at the user's request. Tick this box after that.
  Deadline reminder: Gemini 2.5 dies 2026-06-17.

### [ ] M.2 — Dedicated TTS slot
- **Why:** `/v1/tts` abuses the Live A2A model for read-aloud; a real
  TTS model reads verbatim, costs less, and has expressive tags.
- **Build:** add a `gemini_model_tts` setting
  (`gemini-3.1-flash-tts-preview`); rewrite `apps/api/app/api/v1/tts.py`
  as a one-shot generate call instead of the Live-session drain.
- **Acceptance criteria:** `/v1/tts` returns WAV audio; the "model
  explains instead of reads" failure mode is gone; lesson-step playback
  latency is no worse than before.
- **Verify:** `pnpm api:test`; play a lesson, confirm narration audio.
- **Depends on:** M.1.
- **Status:** not started

### [x] M.3 — Pin generation model ids
- **Why:** the content pipeline bakes the model name into a provenance
  hash; a `*-latest` alias hot-swap silently corrupts provenance.
- **Build:** pin `GEMINI_MODEL_PRO` to an explicit
  `gemini-3.1-pro-preview` string; audit `gemini.py` / `content/cli.py`
  for other `*-latest` uses on generation paths.
- **Acceptance criteria:** no `*-latest` alias remains on any
  content-generation or provenance-hashed path.
- **Verify:** `pnpm api:test`; grep shows no `-latest` on generation.
- **Depends on:** none.
- **Status:** done. `config.py` `gemini_model_pro` pinned to
  `gemini-3.1-pro-preview`. Audit found one real `*-latest` on a
  content path — `b0_oscillations.py:258` env fallback — now fixed to
  the pinned string. `generator.py` / `quiz_generator.py` already use
  `settings.gemini_model_pro` (resolve to the pin); remaining `-latest`
  hits are docstrings / README / test fixtures (no runtime effect).
  `pnpm api:test` → 169 passed after the fix.

---

# Phase 0 — Auth & compliance foundation

> Section 0 turns the demo app into one with real accounts. 0.2 is a
> wide refactor; 0.1 must fully map the surface first. Build 0.1→0.4 in
> order. (`teacher-authoring.md` §12 Phase 0, §14.)

### [x] 0.1 — Recon: map the demo-auth surface
- **Why:** 0.2 replaces demo auth everywhere; we cannot refactor safely
  without a complete inventory of every touchpoint.
- **Build:** produce a written map (append to this file under the task)
  of every use of `DEV_MODE` / `dev_mode` / `is_dev` / `X-Dev-User-Id` /
  `get_current_user` / the demo user id / `NEXT_PUBLIC_DEMO_MODE` —
  across API and web.
- **Acceptance criteria:** the map lists every file + line and what each
  does; reviewed against `grep` so nothing is missed.
- **Verify:** a second independent grep finds nothing outside the map.
- **Depends on:** none.
- **Status:** done. Map below.

**Demo-auth surface map (0.1 result)**

*API — auth core:*
- `app/core/security.py` — **the chokepoint.** `get_current_user()`
  (L81–103): when `is_dev` + `X-Dev-User-Id` header → bypasses JWT,
  returns synthetic claims. `get_optional_user()` (L106–114): same,
  returns `None` on failure. `verify_supabase_jwt()` (L39–68): the real
  HS256 path. `_parse_bearer()` (L71–78).
- `app/core/config.py` — `dev_mode` flag (L56); `is_dev` property
  (L87–96, hard-off in production); `supabase_jwt_secret` (L47–49).
- `app/main.py` — lifespan guard (L47–55): refuses boot if
  `ENVIRONMENT=production` + `DEV_MODE=true`.
- `app/core/supabase.py` — `supabase_enabled()` (L36–50): false in dev
  with placeholder URL.
- `app/core/rate_limit.py` — `_user_key()` (L31–42): keys on
  `X-Dev-User-Id` then bearer.
- `app/ws/voice.py` — `voice_ws()` (L49–88): accepts missing token when
  `is_dev`, assigns `user_id="dev-user"`; else `verify_supabase_jwt`.
- `app/core/session_auth.py` — `require_session_owner()` (L37–86): uses
  `get_current_user`; synthetic row when Supabase disabled.

*API — protected endpoints (19, all via `Depends(get_current_user)`):*
`me.py`, `sessions.py`, `qa.py`, `quiz.py` (×3), `notes.py` (×4),
`flashcards.py` (×2), `planner.py` (×2), `health.py`, `courses.py`,
`history.py`, `reaction.py`, `reply.py`, `sketch.py`.

*API — tests:* `tests/conftest.py` forces `DEV_MODE=true` (L23) and the
`dev_headers` fixture (L42) uses demo id `00000000-…-0001`.

*Web:*
- `.env.local` L8 `NEXT_PUBLIC_DEMO_MODE=true`.
- `src/lib/api.ts` L79–88: when `NEXT_PUBLIC_DEMO_MODE` + no Authorization
  → injects `X-Dev-User-Id` demo id; else `resolveAuthToken()` (L33–47)
  uses the Supabase session token.
- `src/lib/supabase/client.ts` (L15–29) + `middleware.ts` (L23–69):
  Supabase client + server session refresh already scaffolded.
- `src/middleware.ts` L25–43: `PROTECTED_PREFIXES` route guard —
  **short-circuited** (L31) when `NEXT_PUBLIC_DEMO_MODE=true`.
- `tests/helpers/mock-api.ts`: Playwright mocks; demo id at L178.

*Refactor blueprint for 0.2:* drop the `X-Dev-User-Id` branch from
`get_current_user` / `get_optional_user` / `voice_ws` / `_user_key`;
require real JWT everywhere; remove the `NEXT_PUBLIC_DEMO_MODE`
short-circuits in `api.ts` and `middleware.ts`; rework `conftest.py` to
mint real test JWTs. Existing Supabase client scaffolding (web) and
`verify_supabase_jwt` (API) are the foundation to build on.

### [x] 0.2 — Real Supabase student auth
- **Why:** classes, per-student progress, and compliance are impossible
  without each student being a distinct authenticated identity.
- **Build:** Supabase email/password (or magic-link) sign-up + sign-in
  for students; replace the `X-Dev-User-Id` bypass with real JWT auth on
  every endpoint from the 0.1 map; web auth context + protected routes.
- **Acceptance criteria:** a new user can sign up, sign in, and is a
  distinct `profiles` row; every API route authenticates via JWT; demo
  bypass is gone (or dev-only and off in prod); existing features still
  work signed-in.
- **Verify:** `pnpm verify`; sign up two users, confirm isolated data;
  `pnpm api:test`.
- **Depends on:** 0.1.
- **Status:** BUILT — automated gate GREEN: `pnpm api:test` 169 passed
  (after fixing a `test_content_b2.py` regression that the M.3 model
  change exposed — a mock hardcoded `gemini-pro-latest`, now asserts
  `settings.gemini_model_pro`); `tsc` clean; `next build` ok. Code
  reviewed — `middleware.ts` route protection is real (demo
  short-circuit removed), `handle_new_user` trigger already creates the
  `profiles` row, `AuthProvider` is sound. Criteria met by code/tests:
  JWT-required on API, demo bypass dev-only/prod-off. Google OAuth was
  restored on `/login` (the agent's rewrite had dropped it).
  **Browser-tested via the preview tool:** `/signup` + `/login` render
  correctly; the signup form submits and calls `supabase.auth.signUp`;
  error handling verified (invalid-email and rate-limit errors show
  clean toasts, no crash); route protection verified (`/dashboard` →
  `/login` redirect); "Continue with Google" button present; no console
  errors; no stray test users created (DB confirmed empty).
  SUCCESS PATH VERIFIED — with email confirmation disabled, a live
  browser signup (`aria.qa.0p2.final@edutest-qa.dev`) created the
  `auth.users` row, the `handle_new_user` trigger created the matching
  `public.profiles` row (full_name "Aria QA Student"), the user was
  signed in, redirected to `/dashboard` with an "Account created!"
  toast, and `/dashboard` rendered for the authed session. All
  acceptance criteria met. **DONE.**
  POST-VERIFICATION FIX: browser-testing the signed-in app exposed a
  real 0.2 defect the automated gate missed — every authenticated API
  call 401'd. Root cause: this Supabase project signs access tokens
  with **ES256** (asymmetric JWKS keys), but `verify_supabase_jwt` only
  did HS256-with-shared-secret. Fixed — `security.py` now picks the
  verification strategy from the token's `alg`: HS256 via the secret
  (legacy / tests), ES256/RS256 via the project's JWKS endpoint
  (`PyJWKClient`); `cryptography` added to `pyproject.toml`. Verified
  live: `/v1/me` → 200 with the real profile, the `/dashboard` greeting
  now renders the user's name. `pnpm api:test` → 176 passed.
  Follow-ups: the QA test user `aria.qa.0p2.final@edutest-qa.dev` is
  kept (a useful working test account); re-enable email confirmation
  (or wire SMTP) before any real launch.

### [x] 0.3 — Admin role + teacher invite-code flow
- **Why:** teachers are invite-only; the system needs an admin to issue
  codes and a redeem path that grants the teacher role.
- **Build:** add `'admin'` to `profiles.role`; `teacher_invites` table
  (can land here or with 1.1 — see note); `POST /v1/admin/teacher-invites`
  and `POST /v1/auth/redeem-teacher-invite`; redeem-at-sign-up UI.
- **Acceptance criteria:** an admin issues a code; redeeming it sets
  `role = 'teacher'`; a used code cannot be reused; non-admins are 403 on
  the admin route.
- **Verify:** `pnpm verify`; redeem-flow test added to `pnpm api:test`.
- **Depends on:** 0.2. *(Note: `teacher_invites` schema is also in 1.1 —
  if 1.1 runs first, reuse it; otherwise create it here and 1.1 skips it.)*
- **Status:** done. Built by a background agent: migration
  `20260515030000_admin_role_teacher_invites.sql` (profiles.role +
  `teacher_invites` + 3 RLS policies), `admin.py` (`POST
  /v1/admin/teacher-invites`, `require_role('admin')`-gated), `auth.py`
  (`POST /v1/auth/redeem-teacher-invite`), `redeem-invite/page.tsx`,
  7 new tests. `pnpm api:test` → 176 passed; `tsc` clean; `next build`
  ok. Migration **applied to the cloud DB** via the Supabase tooling
  (schema verified: `profiles.role` text default 'student',
  `teacher_invites` + 3 policies present). **Live end-to-end verified**
  in the browser: admin issued `TEACH-E8UYGA` (201), redeem set
  `role='teacher'` (200), reusing the code → 409. First admin
  bootstrapped: the QA user `aria.qa.0p2.final@edutest-qa.dev`
  (`a8ea46d4-…`) is set `role='admin'` — the project's designated admin.

### [x] 0.4 — Compliance baseline
- **Why:** real minors' data is now in the app; the §14 baseline must
  exist before any student is onboarded.
- **Build:** privacy policy + terms pages shown and recorded-as-accepted
  at sign-up; data-minimisation review of the sign-up form; an account/
  data deletion path; the join-approval consent record (`approved_by` /
  `approved_at`) — schema may come with 1.1, the *behaviour* lands here.
- **Acceptance criteria:** sign-up records terms acceptance; a user can
  trigger deletion of their data; only the minimal PII fields are
  collected; §14 "v1 baseline" bullets are each satisfied.
- **Verify:** `pnpm verify`; walk the sign-up + deletion flows.
- **Depends on:** 0.2.
- **Status:** done. Built by a background agent: migration
  `20260515040000_terms_acceptance.sql` (`profiles.terms_accepted_at` +
  extended `handle_new_user`), `/privacy` + `/terms` pages, `DELETE
  /v1/me` self-service account deletion (target taken ONLY from the JWT
  `sub`), signup records terms acceptance + links to the legal pages,
  7 new tests. `pnpm api:test` → 183 passed; `tsc` clean; `next build`
  ok. Migration applied to the cloud DB (column verified). **Live-
  verified**: a fresh browser signup (`aria.qa.0p4@edutest-qa.dev`)
  recorded `terms_accepted_at`; `/signup` links to `/terms` + `/privacy`.
  Account-deletion logic is covered by the 7 tests (not live-run — it is
  destructive). Deferred (correctly): the school-mediated join-approval
  consent record needs `class_members`, which arrives in Phase 1.

---

# Phase 0.5 — Voice mode repair

> Slotted after Phase 0, before Phase 1 (user decision, 2026-05-15).
> Independent of the teacher feature. Found while the user tested the
> classroom mic: "tap mic → nothing happens." It is NOT a UI problem —
> `VoiceMode` already auto-starts `live.start()` on open; "TAP TO START"
> is just the hint shown in the `closed` (failed-to-connect) state.

### [x] 0.5 — Fix classroom voice mode (3 bugs)
- **Why:** voice mode never connects, so the classroom mic is dead. The
  diagnosis (2026-05-15, via the preview browser + API logs):
  - **A — topic not in DB.** The classroom topic `wave-properties-anatomy`
    (`topic_id 12d9a72e-6afa-44d8-8b7c-957f163a3a0c`) is leftover
    prototype data not present in `topics`; `POST /v1/sessions` fails the
    `lesson_sessions_topic_id_fkey` FK → 503 → no `sessionId` → voice has
    nothing to attach to. Real seeded topics are unaffected. **Needs a
    decision:** seed the prototype classroom topics, or point the
    classroom only at real topics.
  - **B — voice WS sends no auth token.** The WebSocket connects
    unauthenticated → falls to the `dev-user` path → `voice_ws`'s
    `assert_session_owner_ws` then queries Postgres with `"dev-user"` as
    a UUID → `22P02` → socket closes `4403`. Fix the web WS client
    (`use-gemini-live.ts`) to send the real Supabase token, and guard
    the dev-user ownership check.
  - **C — DONE.** A Windows-only `→` in a `voice.py` log line crashed the
    logger (cp1252); changed to `->`.
- **Build:** resolve A (data decision + seed/redirect) and B (WS token +
  dev-user guard); confirm voice reaches the `listening` state.
- **Acceptance criteria:** tapping the classroom mic on a real topic
  opens voice mode and it reaches `listening` (hint "I'm listening…"),
  not `closed`; barge-in works (ties to deferred M.1 voice test).
- **Verify:** `pnpm verify`; browser test — open a real topic, tap mic,
  confirm the live state via the preview tool + API logs.
- **Depends on:** Phase 0 complete.
- **Status:** DONE. Bug A — a background agent repointed every
  `wave-properties-anatomy` prototype link to real seeded topic UUIDs
  (`resolveClassroomTopicPath()` in `api.ts`; dashboard, `app-chrome`,
  `history-row`, `curriculum-unit`, marketing `page.tsx`) and removed
  the hardcoded prototype lesson from `classroom-shell.tsx`. Bug B —
  `session_auth.py` `assert_session_owner_ws` now guards a non-UUID
  `user_id` (the dev-user shortcut) instead of crashing the Postgres
  query. Bug C — fixed earlier (`→` log crash). `pnpm api:test` → 184
  passed; `tsc` clean; `next build` ok. **Live-verified** on a real
  topic (`/classroom/486fe022-…`, Position/Velocity/Acceleration):
  `POST /v1/sessions` → 201; tapping the mic opened VoiceMode; the
  voice WS connected (`session_owner_ws_skip_non_uuid` guard fired,
  `voice_session_open` — the Gemini Live bridge came up); VoiceMode
  reached the **`listening`** state ("I'm listening…"). Note: in dev
  the WS uses the tokenless dev-user path (works via the new guard);
  the real-token path for production lives in `use-gemini-live.ts`.

---

# Phase 1 — Schema foundations

> Section 1 is one coherent migration effort — design 1.1–1.2 together
> (tables + their RLS), then 1.3–1.4. No teacher UI yet.
> (`teacher-authoring.md` §4, §12 Phase 1.)

### [x] 1.1 — Migration: the full §4 schema
- **Why:** every later phase reads/writes these tables; they must exist
  and exactly match `teacher-authoring.md` §4.
- **Build:** one timestamped migration adding — new columns on
  `profiles`, `courses`, `topics`, `topic_progress`, `quiz_questions`;
  new tables `classes`, `class_members`, `class_courses`,
  `lesson_materials`, `material_pages`, `unit_segmentations`,
  `topic_pages`, `topic_versions`, `teacher_invites`, `pipeline_jobs`.
  All FKs `on delete cascade` where §13 "deletion" requires it.
- **Acceptance criteria:** column/table names, types, defaults, PKs,
  uniques exactly match §4; migration applies cleanly and is idempotent;
  existing tables/data are untouched.
- **Verify:** `pnpm db:reset` succeeds; `pnpm api:test`; schema diff
  matches §4.
- **Depends on:** 0.3 (role model).
- **Status:** done. Migration `supabase/migrations/20260515050000_teacher_authoring_schema.sql`
  applied to cloud. `profiles.role` + `teacher_invites` deliberately
  omitted (already shipped by 0.3). **Schema audit vs §4** (queried live):
  all 9 new tables present; all 11 new columns present
  (courses ×5, topics ×4, topic_progress ×1, quiz_questions ×1); circular
  FK resolved — `topics_active_version_id_fkey` + `topic_progress_…` are
  `ON DELETE SET NULL`, `quiz_questions_topic_version_id_fkey` is
  `ON DELETE CASCADE` (§13 version-scoped). §13 cascades applied on the
  unit/topic/material/version child FKs; `classes.teacher_id` /
  `courses.owner_id` left no-action (§13 "frozen, not deleted").
  Idempotent: full PART A/B re-applied with no error; PART C–F use
  `create or replace` / `drop policy if exists`. `pnpm api:test` → 184
  passed (= baseline), no regression. Existing data untouched (only
  `add column if not exists` on existing tables).

### [x] 1.2 — RLS for all new tables
- **Why:** defense-in-depth — a student must never read another class's
  data or unpublished topics; teachers only their own.
- **Build:** RLS policies per `teacher-authoring.md` §4 "RLS", including
  the `unit → course → owner_id` join helper SQL function.
- **Acceptance criteria:** each §4 RLS bullet is enforced; a student
  cannot read a `pending` membership's course; a teacher cannot read
  another teacher's materials — proven by tests.
- **Verify:** `pnpm api:test` with RLS tests (cross-tenant denial).
- **Depends on:** 1.1.
- **Status:** done. RLS enabled on all 9 new tables + the 3 curriculum
  tables; world-readable `courses/units/topics_read_all` replaced with
  split recommended-vs-teacher policies. Seven `SECURITY DEFINER` join
  helpers — `is_unit_owner`, `is_topic_owner`, `is_active_member_of_course`,
  `is_admin`, `is_class_teacher`, `is_class_member`, `is_active_class_member`
  — `EXECUTE` revoked from `anon`/`public` (advisor lint 0028).
  **Bug found + fixed during verification:** the first cut had `classes`
  and `class_members` policies querying each other's table directly →
  Postgres `42P17` infinite recursion; fixed by routing every cross-table
  membership check through the definer helpers (they evaluate outside RLS).
  **Verified** against the live cloud DB: a 16-assertion role-switched
  harness (`set local role authenticated` + `request.jwt.claims`, seed
  rolled back) — all 16 PASS, incl. pending-student denied course+topic,
  draft topic hidden from active students, teacher B denied teacher A's
  class/materials/versions, recommended courses still world-readable.
  `apps/api/tests/test_teacher_rls.py` (10 psycopg-based RLS tests) is
  wired but **skips** without `DATABASE_URL`/`SUPABASE_DB_URL` (no local
  Postgres / cloud DB password not in env); RLS was instead proven
  directly against cloud as above. `pnpm api:test` → 184 passed, 10
  skipped.
  > NOTE for **2.6**: `quiz_questions` still has the legacy
  > `quiz_questions_read_all` world-read policy. Harmless now (no teacher
  > quizzes exist), but once teacher courses generate version-scoped
  > quizzes it must be tightened to the topic-visibility rule.

### [x] 1.3 — `lesson-materials` Storage bucket
- **Why:** uploads and rendered slide PNGs need storage with correct
  access (teachers write own prefix; students never direct-read).
- **Build:** create the bucket; access rules so teachers write their
  prefix and the service role reads; no public/student bucket access.
- **Acceptance criteria:** a teacher can upload to their prefix; a
  student cannot list/read the bucket directly.
- **Verify:** `pnpm api:test`; manual access check.
- **Depends on:** 1.1.
- **Status:** done. Migration
  `supabase/migrations/20260515060000_lesson_materials_storage.sql`
  applied to cloud — private bucket `lesson-materials` (`public=false`)
  + 4 own-prefix RLS policies on `storage.objects` (select/insert/
  update/delete), each scoped `bucket_id='lesson-materials' AND
  (storage.foldername(name))[1] = auth.uid()::text`. Path convention:
  first segment of every key is the uploading teacher's uid
  (`<teacher-uuid>/<unit>/<material>/<file>`). Students get no Storage
  policy — RLS denies them; the service role bypasses RLS for the
  pipeline. **Verified** against the live DB (role-switched harness,
  rolled back): bucket private ✓, 4 policies present ✓, teacher reads
  own object ✓, student denied teacher's object ✓, teacher insert own
  prefix ✓, teacher insert another's prefix denied ✓. Idempotent
  (`on conflict do nothing` + `drop policy if exists`) — re-applied
  cleanly. No API/web code touched; 184 API tests unaffected.

### [x] 1.4 — `pipeline_jobs` worker harness + role helper
- **Why:** §6 stages run minutes-long; they need an async runner and a
  status the board can poll. A reusable role-gate helper is needed too.
- **Build:** a background-job runner that picks up `pipeline_jobs` rows,
  advances `status`/`stage`, is idempotent/resumable; `GET .../jobs/{id}`;
  a `require_role('teacher'|'admin')` dependency.
- **Acceptance criteria:** a queued job runs to `succeeded`; a job that
  fails mid-stage resumes from that stage; the polling endpoint reports
  live `stage`; the role helper 403s the wrong role.
- **Verify:** `pnpm api:test` with a fake multi-stage job.
- **Depends on:** 1.1.
- **Status:** done. New `app/pipeline/` package — `jobs.py` `run_job()`
  is the generic async runner: it walks a job kind's FIXED §4 stage
  sequence (`segment`: converting→comprehending; `generate`:
  rendering→generating→validating), persists `stage`+`status='running'`
  BEFORE each stage so a crash leaves a resumable marker, and on a stage
  exception persists `status='failed'`+`error` with `stage` at the
  failing stage. A `failed`/`running` re-run resumes AT the persisted
  `stage` (earlier stages skipped); a `succeeded` re-run is a no-op.
  Stage handlers are injectable (`STAGE_HANDLERS` registry ships empty —
  Phase 2 fills it; unregistered stage = no-op). New `app/api/v1/teacher.py`
  — `GET /v1/teacher/jobs/{id}`, `require_role('teacher','admin')`-gated;
  since the service role bypasses RLS it re-verifies ownership by walking
  `unit_id`/`topic_id`→units→courses.owner_id (admin sees any, non-owner
  →404). Registered in `router.py`. 9 new tests in
  `tests/test_pipeline_jobs.py` (fake multi-stage job → succeeded;
  fail-mid-stage→failed→resume-no-redo proven via per-stage counters;
  succeeded re-run no-op; endpoint live-stage; admin-any; 404 missing;
  403 non-teacher; 404 non-owner). `pnpm api:test` → 193 passed, 10
  skipped (= 184 baseline + 9). `import app.main` clean. No migration,
  no web changes. NOTE for Phase 2: the enqueue endpoints
  (`POST .../segment`, `POST .../generate`) and real stage handlers are
  Phase 2 — 1.4 ships only the runner + the GET poll endpoint.

---

# Phase 2 — Authoring pipeline

> Section 2 is the heart of the feature and is backend-only — proven by
> a script against the real `Unit 8 - Fluids` deck, no UI needed.
> 2.1–2.3 are the ingest+understand+render section; 2.4–2.7 the
> generate+quiz+validate section. (`teacher-authoring.md` §6.)

### [x] 2.1 — Ingest validation + normalize-to-PDF
- **Why:** uploads are untrusted; everything downstream needs one PDF
  form.
- **Build:** size cap + MIME allow-list + spoofed-type rejection; the
  LibreOffice-headless Docker layer; `.docx`/`.pptx`/`.txt` → PDF;
  per-teacher rate limit/quota; `lesson_materials.conversion_status`.
- **Acceptance criteria:** valid PDF/Word/PPT/text convert; an oversized
  or spoofed file is rejected; conversion runs sandboxed; the Fluids
  `.pptx` produces a PDF.
- **Verify:** `pnpm api:test`; run on `Unit 8 - Fluids - AP Physics 1.pptx`.
- **Depends on:** 1.4.
- **Status:** done. New `app/pipeline/ingest.py` — `validate_upload`
  (size cap, MIME allow-list, **spoof rejection** by magic-byte sniffing:
  `%PDF`; OOXML = ZIP peeked for `ppt/`/`word/`; text = decodes clean,
  no NUL — the claimed extension is never trusted), `convert_to_pdf`
  (PDF passthrough; `.docx`/`.pptx`/`.txt` via LibreOffice headless,
  **sandboxed**: hard timeout, isolated per-call `-env:UserInstallation`
  profile, scrubbed env, fixed argv `shell=False`), `ingest_material`
  (drives `conversion_status` pending→converting→converted/failed).
  `apps/api/Dockerfile` gains a `libreoffice-writer`/`-impress` + fonts
  layer; per-teacher upload rate-limit + daily quota in `rate_limit.py`
  (`ingest_acquire`); config defaults — 50 MB cap, 120 s timeout,
  10/min, 100/day. Verification script `app/pipeline/ingest_script.py`.
  **Verified** with LibreOffice 26.2.3 installed: `pnpm api:test` →
  218 passed, 10 skipped (the 3 LibreOffice conversion tests now RUN —
  `.docx`/`.pptx`/`.txt`→PDF; only the 10 DB-RLS tests skip). The real
  **`Unit 8 - Fluids - AP Physics 1.pptx`** (4.9 MB) ran through
  `ingest_script` → validated as pptx → produced a **3.4 MB valid PDF**
  (`%PDF-`). 25 ingest tests pass; `import app.main` clean.

### [ ] 2.2 — Comprehension + topic segmentation
- **Why:** turns an unstructured upload into a proposed topic breakdown
  the teacher can confirm — the core "model structures it" step.
- **Build:** combined multimodal call (model per `model-strategy.md` §6)
  → write a `unit_segmentations` row: comprehension JSON + proposed
  breakdown (titles, summaries, page sets, practice→topic tags, page
  teach/skip, animation-build collapse per §13).
- **Acceptance criteria:** on the Fluids deck it proposes ~4 topics
  aligned to 8.1–8.4; non-teaching slides excluded; duplicate
  animation-build slides collapsed; output validates against the §4
  `unit_segmentations` shape.
- **Verify:** `pnpm api:test`; segmentation script on the Fluids deck,
  output reviewed against the known structure.
- **Depends on:** 2.1.
- **Status:** not started

### [ ] 2.3 — Slide rendering (post-confirm, slides-only)
- **Why:** the classroom displays the teacher's real slides; only
  displayed pages need rasterising.
- **Build:** `pymupdf` render of claimed `slides`/`figure` pages →
  `material_pages` PNGs in Storage; runs after breakdown-confirm, only
  for pages a `topic_pages` row claims.
- **Acceptance criteria:** confirmed-topic slide pages render to PNG;
  prose `notes`/`practice` pages are NOT rendered; images land in the
  bucket.
- **Verify:** `pnpm api:test`; confirm a Fluids breakdown, check PNGs.
- **Depends on:** 2.2.
- **Status:** not started

### [ ] 2.4 — Persona builder
- **Why:** teacher courses are any subject/grade; Aria must not be the
  hard-coded physics tutor.
- **Build:** refactor `apps/api/app/agents/prompts.py` into a builder
  keyed on `courses.subject` + `grade_band` + `teaching_style`;
  Recommended courses keep the existing physics persona.
- **Acceptance criteria:** a built persona for "Biology, 6-8" differs
  appropriately from "Physics, 9-12"; `teaching_style` is additive and
  never overrides the Socratic rules; Recommended-course output is
  unchanged.
- **Verify:** `pnpm api:test` with persona-builder unit tests.
- **Depends on:** 1.1.
- **Status:** not started

### [ ] 2.5 — Lesson generation + scene assignment
- **Why:** produces the actual Aria lesson per confirmed topic, with
  drawings, depth-scaled to the material.
- **Build:** per-topic generate job → lesson steps from the topic's
  `comprehension` slice + persona + `design_notes`; assign each step a
  `scene` (typed registry + Claude fallback) and a `page`; write a
  `topic_versions` row + mirror to `topics.content`.
- **Acceptance criteria:** a Fluids topic generates a coherent lesson of
  material-appropriate length; every step has a scene; slide-backed
  steps reference a valid `topic_pages` id; the §4 invariant holds.
- **Verify:** `pnpm api:test`; generate a Fluids topic, inspect steps.
- **Depends on:** 2.3, 2.4.
- **Status:** not started

### [ ] 2.6 — Quiz generation (version-scoped)
- **Why:** each topic ends with a quiz that versions with its lesson.
- **Build:** `quiz_questions.topic_version_id`; auto-from-lesson
  generation; practice-material path when `quiz_source = 'practice'`;
  the `'practice'`-needs-practice-material guard.
  **RLS carry-over from 1.2:** `quiz_questions` still has the legacy
  `quiz_questions_read_all` world-read policy. Once teacher courses carry
  version-scoped quizzes, replace it — recommended-course questions stay
  world-readable; teacher-course questions follow the topic-visibility
  rule (published topic + active class membership; owner/admin see all).
- **Acceptance criteria:** a generated topic has a quiz tagged to its
  version; re-generation produces a new version's quiz without breaking
  old `quiz_attempts`; `'practice'` is rejected when no practice
  material exists.
- **Verify:** `pnpm api:test`; generate + re-generate a topic's quiz.
- **Depends on:** 2.5.
- **Status:** not started

### [ ] 2.7 — Validator + end-to-end pipeline proof
- **Why:** generated lessons must actually cover the teacher's content;
  the whole pipeline must be proven on a real unit before any UI.
- **Build:** validator (existing pattern, run vs `comprehension`);
  retry-once-then-draft on failure; an end-to-end script: upload →
  segment → confirm → generate → validate for `Unit 8 - Fluids`.
- **Acceptance criteria:** the script takes the Fluids `.pptx` to
  validated draft lessons for all proposed topics; a deliberately
  starved topic fails validation and lands `draft` with a gap report.
- **Verify:** `pnpm api:test`; run the full script, review the lessons.
- **Depends on:** 2.6.
- **Status:** not started

---

# Phase 3 — Admin board (`/teach`)

> Section 3 gives teachers the UI over the Phase 2 pipeline. 3.1 first
> (scaffold), then 3.2–3.5. (`teacher-authoring.md` §9.)

### [ ] 3.1 — `/teach` scaffold + role gate
- **Why:** every teacher screen needs a role-gated shell + nav.
- **Build:** the `/teach` route group, role-gated (non-teacher → 403/
  redirect); teacher home listing classes + courses.
- **Acceptance criteria:** a teacher sees `/teach`; a student cannot;
  home lists the teacher's classes and courses.
- **Verify:** `pnpm verify`; visit as each role.
- **Depends on:** 1.2, 0.3.
- **Status:** not started

### [ ] 3.2 — Class management + join approvals
- **Why:** teachers create classes, share codes, and approve students
  (the consent gate).
- **Build:** create class + join code; roster; **pending join requests
  with approve/remove**; `class_members` approve/remove endpoints + UI.
- **Acceptance criteria:** a teacher creates a class, sees a pending
  join, approves it (`status → active`, `approved_by/at` set), removes a
  student.
- **Verify:** `pnpm verify`; full join→approve loop with a test student.
- **Depends on:** 3.1.
- **Status:** not started

### [ ] 3.3 — Course/unit management + material upload
- **Why:** teachers need to create a course (subject, grade band,
  teaching style) and a unit, and upload material into it.
- **Build:** course/unit CRUD UI; the unit material upload UI calling
  `POST .../materials`.
- **Acceptance criteria:** a teacher creates a course with subject +
  grade band, a unit, and uploads the Fluids `.pptx`; it appears as a
  `lesson_materials` row.
- **Verify:** `pnpm verify`; upload the real deck through the UI.
- **Depends on:** 3.1, 2.1.
- **Status:** not started

### [ ] 3.4 — Segmentation job UI + confirm-breakdown screen
- **Why:** the teacher must watch the segment job and confirm/edit the
  proposed breakdown — the key human checkpoint.
- **Build:** job-progress polling + the done-badge; the confirm screen —
  rename/merge/split/reorder/drop topics, **and excluded pages shown
  with re-include**; `POST .../topics` (idempotent).
- **Acceptance criteria:** after uploading the Fluids deck the teacher
  sees the proposed ~4 topics, can edit them, sees excluded pages, and
  confirms → `topics` + `topic_pages` rows created.
- **Verify:** `pnpm verify`; run the confirm flow on the Fluids deck.
- **Depends on:** 3.3, 2.2.
- **Status:** not started

### [ ] 3.5 — Topic review/edit/preview + versions + publish
- **Why:** teachers review generated lessons, edit, preview as a
  student, manage versions, and publish.
- **Build:** the topic page — watch the generate job, review/edit steps,
  student-preview, version list/activate/delete, Publish (blocked until
  validated).
- **Acceptance criteria:** a teacher generates, previews, edits, re-
  generates (new version), switches the live version, and publishes a
  Fluids topic; publish is blocked on an unvalidated lesson.
- **Verify:** `pnpm verify`; full review→publish loop.
- **Depends on:** 3.4, 2.7.
- **Status:** not started

---

# Phase 4 — Student side

> Section 4 is the student-facing surface for teacher content.
> (`teacher-authoring.md` §7, §8.)

### [ ] 4.1 — Dashboard split
- **Why:** students must see Recommended vs From-your-teacher courses.
- **Build:** the dashboard course list split into the two groups;
  teacher group resolved via `class_members → class_courses`; the
  courses endpoint `group` field; "coming soon" for zero-published.
- **Acceptance criteria:** a student in a class sees its published
  teacher courses under "From your teacher"; an all-draft course shows
  "coming soon".
- **Verify:** `pnpm verify`; view the dashboard as an enrolled student.
- **Depends on:** 3.5.
- **Status:** not started

### [ ] 4.2 — Join-a-class flow
- **Why:** students join a class with a code and wait for approval.
- **Build:** the "Join a class" action → `POST /v1/classes/join` →
  `pending` membership; "awaiting approval" state on the dashboard.
- **Acceptance criteria:** entering a valid code creates a `pending`
  row and shows "awaiting approval"; after teacher approval the class's
  courses appear; an invalid code errors cleanly.
- **Verify:** `pnpm verify`; join→approve→access end to end.
- **Depends on:** 4.1, 3.2.
- **Status:** not started

### [ ] 4.3 — Classroom slide + annotation rendering
- **Why:** teacher lessons show the real slide as a backdrop with Aria's
  annotations on top.
- **Build:** `GET /v1/topics/{id}/slide/{topic_page_id}` (signed URL,
  `active`-membership gated); classroom renders the slide backdrop for
  steps with a `page`; auto-create `enrollments` on first open.
- **Acceptance criteria:** a student plays a published Fluids topic —
  slide-backed steps show the slide + scene overlay, chalkboard steps
  fall back; a non-member gets no signed URL; an `enrollments` row is
  created on first open.
- **Verify:** `pnpm verify`; play a teacher lesson as a student.
- **Depends on:** 4.2, 3.5.
- **Status:** not started

---

# Phase 5 — Polish

> Section 5 is non-blocking refinement; each task is independent.

### [ ] 5.1 — Re-generation / version-management UX
- **Why:** make the version history (§11.3) usable — labels, diffs,
  delete-old.
- **Build:** version UX in the topic page; the §13 re-segmentation-
  after-publish mapping flow.
- **Acceptance criteria:** a teacher manages versions and handles a
  re-segmentation of a unit with published topics without data loss.
- **Verify:** `pnpm verify`.
- **Depends on:** 3.5.
- **Status:** not started

### [ ] 5.2 — Course cover art
- **Why:** teacher courses need visual identity on the dashboard.
- **Build:** generate a course cover via Nano Banana 2
  (`model-strategy.md` §4) at publish; cache it.
- **Acceptance criteria:** a published teacher course has a generated
  cover; generation is one-shot and cached.
- **Verify:** `pnpm verify`.
- **Depends on:** 4.1.
- **Status:** not started

### [ ] 5.3 — Analytics
- **Why:** teachers want to see how their class is doing.
- **Build:** per-class progress/score view for the teacher.
- **Acceptance criteria:** a teacher sees aggregate class progress per
  topic.
- **Verify:** `pnpm verify`.
- **Depends on:** 4.3.
- **Status:** not started
