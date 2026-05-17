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
| 2 — Authoring pipeline | 2.1–2.8 | 8/8 — COMPLETE (ingest → segment → confirm → render → persona → generate → quiz → validate + e2e + practice extraction) |
| 3 — Admin board | 3.1–3.6 | 6/6 — COMPLETE (scaffold · class mgmt · course/unit + upload · segmentation + confirm · topic generate/publish · assign courses to classes) |
| 4 — Student side | 4.1–4.3 | 2/3 — 4.1 (dashboard split) · 4.2 (join-a-class) done |
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

### [x] 2.2 — Comprehension + topic segmentation
- **Why:** turns an unstructured upload into a proposed topic breakdown
  the teacher can confirm — the core "model structures it" step.
- **Build:** combined multimodal call (model per `model-strategy.md` §6)
  → write a `unit_segmentations` row: comprehension JSON + proposed
  breakdown (titles, summaries, page sets, practice→topic tags, page
  teach/skip, animation-build collapse per §13).
- **Acceptance criteria:** on the Fluids deck it proposes lesson-sized
  topics that group cleanly under CED 8.1–8.4 (granularity decision
  2026-05-16: one topic = one lesson-sized beat, NOT one CED topic — the
  doc's earlier "~4" estimate assumed CED-grained topics; a real 76-slide
  deck naturally has ~10 lesson-sized beats, and the teacher can still
  merge/split at the §5.7 confirm step); non-teaching slides excluded;
  duplicate animation-build slides collapsed; output validates against
  the §4 `unit_segmentations` shape.
- **Verify:** `pnpm api:test`; segmentation script on the Fluids deck,
  output reviewed against the known structure.
- **Depends on:** 2.1.
- **Status:** done. `app/pipeline/segment.py` (`comprehend_unit` core +
  `segment_unit` DB function), `segment_script.py`, the `Comprehension`/
  `ProposedBreakdown`/`UnitSegmentation` Pydantic schema (doubles as the
  Gemini `response_schema`) for the §4 `comprehension`/`proposed`
  columns, `GeminiService.generate_from_pdfs` (one combined multimodal
  PDF call), config `gemini_model_segment` (`gemini-3-flash-preview`) +
  `segment_escalate_pages` (60) / `segment_chunk_pages` (200) knobs. The
  prompt instructs every §13 case (teach/skip exclusion, animation-build
  collapse keeping the final slide, recap flagging, thin-section
  flagging, practice tagging, empty-breakdown-with-reason). 14
  mocked-Gemini tests; `pnpm api:test` → 232 passed, 10 skipped (218
  baseline + 14). **Live-verified** on the real `Unit 8 - Fluids - AP
  Physics 1.pptx` (76 slides): escalated to `gemini-3.1-pro-preview`
  (>60 pages), 64 teaching / 12 excluded pages, output validated the §4
  schema, 29 practice questions tagged. It proposed 10 lesson-sized
  topics that group cleanly under CED 8.1–8.4 (Density ×2; Pressure ×3;
  Buoyancy ×2; Fluid flow ×3). Per the 2026-05-16 granularity decision
  the doc's "~4" estimate was corrected (see Acceptance criteria) and
  the finer breakdown accepted.

### [x] 2.3 — Slide rendering (post-confirm, slides-only)
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
- **Status:** done. New `app/pipeline/render.py` — `render_pdf_pages`
  (pure core: PDF bytes + 0-based page indices → `{idx: png_bytes}` via
  `pymupdf`, resolution config-driven) + `render_topic(topic_id)` (DB
  function: load the topic's `topic_pages`, render each DISTINCT
  slide/figure page from its material's `normalized_pdf`, upload the PNG
  to the `lesson-materials` bucket, upsert a `material_pages` row).
  `render_script.py` verification script. Config knob
  `render_dpi` (default 150 — a ~1275×1650 PNG, sharp for a §7 backdrop).
  **Idempotency:** the `material_pages` PK `(material_id, idx)` — pages
  already in `material_pages` are skipped, and the write is an `upsert`
  on that PK, so a re-run / two topics sharing a page render it once.
  **"notes/practice never rendered":** prose pages never get a
  `topic_pages` row, AND the renderer additionally filters to
  `role in ('slide','figure')` defensively. `pymupdf` added to
  `pyproject.toml`. 12 mocked tests in `tests/test_render.py`; `pnpm
  api:test` → 244 passed, 10 skipped (232 baseline + 12). `import
  app.main` clean. No migration, no web changes. The §10 confirm-
  breakdown step that writes `topic_pages` rows is a later task — 2.3
  only CONSUMES them; the script renders pages from a PDF directly.

### [x] 2.4 — Persona builder
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
- **Status:** done. `build_persona(subject, grade_band, teaching_style)`
  added to `app/agents/prompts.py` (all three default `None`). All-`None`
  (Recommended/OpenStax course) returns the EXACT existing
  `ARIA_BASE_PERSONA` constant — byte-identical, asserted by a test —
  so tutor/voice/Socratic output is unchanged. Non-null assembles a
  persona: `subject` sets the domain framing; `grade_band`
  (`K-2|3-5|6-8|9-12`) sets vocabulary / sentence length / pacing (K-2 =
  short sentences + simplest words + gentle pacing; 9-12 = domain
  vocabulary + rigour). `teaching_style` is a separate appended block,
  framed as additive with the Socratic core re-asserted right after, so
  a hostile style ("just give the answer") cannot strip the
  never-give-the-answer / one-idea-per-step rules. `ARIA_BASE_PERSONA` /
  `SOCRATIC_RULES` constants left untouched; no call site needed changes
  (no caller has course params yet — the `None` default keeps them on
  the unchanged Recommended persona). 9 new tests in
  `tests/test_persona.py`. `pnpm api:test` → 253 passed, 10 skipped
  (244 baseline + 9). `import app.main` clean. No migration, no web
  changes.

### [x] 2.5 — Lesson generation + scene assignment
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
- **Status:** BUILT — `app/pipeline/generate.py` (`generate_lesson` core +
  `generate_topic` DB function + `slice_comprehension`), `generate_script.py`
  verification script, 22 mocked-Gemini tests in `tests/test_generate.py`.
  CORE decoupled from the DB: `generate_lesson` takes the topic's
  title/summary/`comprehension_slice`/`design_notes`/persona params/
  `topic_pages` directly. Persona via task 2.4's `build_persona`; depth
  scales (`GeneratedLesson` has NO `max_length` — 8-step rubric dropped);
  scenes reuse the EXISTING system — `scene_tagger.tag()` typed registry
  first, the `generate_scene_svgs` Claude `custom-svg` drawer second
  (injected via `scene_drawer`), a guaranteed text-board scene last, so
  EVERY step has a non-null scene. A step's `page` is set to a real
  `topic_pages` row `id` from a 1-based model `page_ref`; 0/out-of-range →
  no `page` → chalkboard. `generate_topic` writes a `topic_versions` row,
  sets `topics.active_version_id`, and mirrors the SAME content into
  `topics.content` (§4 invariant). `pnpm api:test` → 275 passed, 10 skipped
  (253 baseline + 22). `import app.main` clean. No migration, no live model
  call, no web changes. The live Fluids generation is run by the
  orchestrator via `generate_script.py` (one PRO-model call).

### [x] 2.6 — Quiz generation (version-scoped)
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
- **Status:** done. `app/pipeline/quiz.py`: `generate_quiz_set` (auto
  CORE — reuses the existing `QuizGenerator` against the topic's §2.2
  `comprehension` slice, decoupled from the DB), `practice_quiz_set` +
  `practice_tags_for_topic` (practice CORE), `generate_quiz(topic_id)`
  (DB function). `generate_quiz` loads the topic's `quiz_source` +
  `active_version_id`, runs the auto or practice path, and writes a fresh
  `quiz_questions` set with `topic_version_id = active_version_id`. The
  delete that clears room is SCOPED to `(topic_id, active_version_id)`,
  so a re-generate after a new `generate_topic` version writes a NEW set
  under the NEW version and LEAVES the old version's rows (+ their
  `quiz_attempts`) untouched. The `practice` guard rejects with
  `QuizError('no_practice_material')` when the unit has no `practice`
  tags for the topic (or <3 usable questions). RLS migration
  `20260516000000_quiz_questions_rls.sql` — drops `quiz_questions_read_all`,
  adds `quiz_questions_read_recommended` (origin='recommended' →
  world-read) + `quiz_questions_read_teacher` (owner/admin all; active
  member only on a published topic), mirroring the
  `topics_read_recommended`/`_teacher` pair, reusing `is_admin` /
  `is_active_member_of_course`. `quiz_script.py` verification script.
  15 new mocked-Gemini tests in `tests/test_quiz_generation.py`. `pnpm
  api:test` → 290 passed, 10 skipped (275 baseline + 15; the 10
  `test_teacher_rls.py` skips need a live Postgres role). `import
  app.main` clean. Migration created but NOT applied (orchestrator
  applies it); no live model call. Practice-question→`quiz_questions`
  mapping is underspecified in §4 (the `practice_tags` shape carries only
  a `question_label`, not a structured MCQ) — see the report's judgment
  call: the practice CORE consumes already-structured MCQs + the tags as
  the topic FILTER. **Verified by the orchestrator:** RLS migration
  applied to the cloud DB; a role-switched harness (rolled back) — 5/5
  PASS: recommended quiz questions stay world-readable, a draft-teacher
  topic's questions are hidden from an active student, a non-member is
  denied a published-teacher question, the owner-teacher sees own
  (published + draft). Live `quiz_script.py` run produced a clean
  3-question MCQ quiz on the Fluids "Buoyancy & Archimedes" topic.
  **GAP flagged for review:** the `practice` path consumes
  already-structured MCQs — the worksheet-PDF → structured-question
  extraction is NOT built and is not a named task in this plan; it needs
  a home (a Phase 3 task, or a new task) before `quiz_source='practice'`
  is end-to-end usable. The `'auto'` path (the default) is complete.

### [x] 2.7 — Validator + end-to-end pipeline proof
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
- **Status:** done (2026-05-16).
  `app/pipeline/validate.py` — `validate_lesson` is the §6 MODEL-GRADED
  coverage check (the PRO model grades each key point covered/weak/missing
  against the topic's `comprehension` slice); `generate_and_validate` is
  the retry-once-then-draft flow (generate → validate, retry ONCE on
  failure, topic ends `status='draft'` either way; a second failure
  surfaces the gap report on the topic's latest `generate` job and on the
  returned result). `app/pipeline/confirm.py` `confirm_breakdown`
  materialises `topics` + `topic_pages` from the latest
  `unit_segmentations.proposed`, IDEMPOTENT via the stable key `topics.n`.
  `app/pipeline/e2e_script.py` chains ingest→segment→confirm→generate→
  validate on the real Fluids deck off a fixed-slug demo course
  (`e2e-fluids-demo`, re-runnable; the demo teacher is a real auth user
  created via the Auth admin API).
  >
  > **Two pipeline bugs found by the live e2e were fixed.** *Bug A* — the
  > PRO model occasionally emits a `tts` past the 120-char cap, a
  > non-retryable schema failure that aborted the whole multi-topic run;
  > the `GeneratedStep.tts` cap is relaxed to 240 (the prompt still asks
  > ≤120 as the quality target). *Bug B* — `comprehension.sections` carry
  > no per-topic linkage, so every topic was graded against all ~16
  > unit-wide key points ("Density" scored `covered=1/gaps=15`, no topic
  > could validate); fixed per the user's decision — `ProposedTopic` now
  > carries its own `key_points` (a §2.2 schema + prompt change), and both
  > generation and validation slice from the topic's OWN points
  > (`topics.n` → `proposed.topics[n-1]`). `slice_comprehension` is kept
  > unchanged for `quiz.py`'s auto path.
  >
  > **Starved-topic mechanism reworked.** Emptying the generator's
  > comprehension slice does NOT starve it — the generator also reads the
  > slide images, so a "starved" lesson still validated. Replaced:
  > `generate_and_validate` takes a `validation_slice` override and the
  > e2e grades the starved topic against the WHOLE unit's key points,
  > deterministically guaranteeing real gaps.
  >
  > **Acceptance criteria — verified by the live e2e (2026-05-16, exit 0):**
  > (1) all 6 proposed Fluids topics generated VALIDATED draft lessons —
  > one ("Buoyancy") exercised the retry (`gaps=1` → regenerate →
  > `gaps=0`); (2) the starved topic graded against 22 unit-wide key
  > points scored `covered=4/gaps=18`, retried, and landed `draft` with an
  > 18-point gap report. `pnpm api:test` → 313 passed, 10 skipped (306
  > baseline + 7 new tests). `pnpm verify` → phase-1 17/17, phase-2 9/9,
  > ALL CHECKS PASS. No migration, no web changes. (Build-harness fix
  > committed separately: the verify scripts hardcoded POSIX `.venv/bin`
  > paths — now cross-platform — and verify-phase-2 now accepts a 307
  > auth-redirect on Phase-0-gated routes.)

### [x] 2.8 — Worksheet question extraction (practice quiz source)
- **Why:** 2.6's `quiz_source='practice'` path consumes already-structured
  MCQs — nothing yet turns a teacher's uploaded practice worksheet into
  them, so `quiz_source='practice'` is not usable end-to-end. (Added
  2026-05-16 — user decision: the practice path gets its own Phase 2 task,
  built before Phase 3.)
- **Build:** extract questions from a unit's `practice`-classified
  material — for each §2.2 `practice_tags` entry, pull the real question
  from the worksheet PDF page and produce a structured MCQ
  (`prompt`/`choices`/`correct_idx`/`explanation`); feed them into 2.6's
  `generate_quiz` practice path (the `practice_questions` argument).
- **Acceptance criteria:** a unit with a practice worksheet yields
  structured MCQs tagged to the right topic; a topic with
  `quiz_source='practice'` builds its quiz from them; a question with no
  clear answer key is flagged, not invented.
- **Verify:** `pnpm api:test`; run against a practice worksheet (the
  Fluids deck's 2.2 run found 29 practice tags — usable as the fixture).
- **Depends on:** 2.6, 2.7.
- **Status:** done (2026-05-16).
  `app/pipeline/practice_extract.py` — `extract_practice_questions` is the
  pure core (worksheet PDFs + the §2.2 `practice_tags` in → a
  `PracticeExtractResult` out): it groups the tags by `material_idx`, makes
  ONE PRO-model `generate_from_pdfs` call per worksheet, and converts each
  returned question to either a usable `PracticeQuestion` (reused from
  `quiz.py` — the exact type `generate_quiz`'s practice path consumes) or a
  `FlaggedQuestion`. `extract_unit_practice` is the DB wrapper — loads the
  unit's latest segmentation's `practice_tags` + its `lesson_materials`
  (ordered by `uploaded_at`, so `material_idx` aligns), downloads the
  worksheet PDFs, runs the core. `practice_extract_script.py` is the live
  proof. NO HTTP endpoint, NO migration, NO web changes — the output is an
  in-memory `list[PracticeQuestion]` handed to `generate_quiz`.
  >
  > "Flag, don't invent" (acceptance criterion 3) is enforced at two
  > layers: the model marks a question `extractable=false` when the
  > material shows no determinable answer, and any `extractable=true` MCQ
  > that fails the `QuizQuestion` schema is converted to a `FlaggedQuestion`
  > rather than crashing the run. The consumer chain — the emitted
  > `PracticeQuestion`s feeding `generate_quiz(quiz_source='practice')` — is
  > covered by a test.
  >
  > **Verified.** `pnpm api:test` → 325 passed, 10 skipped (313 baseline +
  > 12 new tests). `pnpm verify` → 17/17 + 9/9, ALL CHECKS PASS. Live
  > `practice_extract_script` on the real Fluids unit (29 practice tags):
  > 23 extracted as structured MCQs (real worked-solution answers), 6
  > flagged — 4 genuinely free-response, 2 over-length prompts — zero
  > answers invented.

---

# Phase 3 — Admin board (`/teach`)

> Section 3 gives teachers the UI over the Phase 2 pipeline. 3.1 first
> (scaffold), then 3.2–3.5. (`teacher-authoring.md` §9.)

### [x] 3.1 — `/teach` scaffold + role gate
- **Why:** every teacher screen needs a role-gated shell + nav.
- **Build:** the `/teach` route group, role-gated (non-teacher → 403/
  redirect); teacher home listing classes + courses.
- **Acceptance criteria:** a teacher sees `/teach`; a student cannot;
  home lists the teacher's classes and courses.
- **Verify:** `pnpm verify`; visit as each role.
- **Depends on:** 1.2, 0.3.
- **Status:** done (2026-05-16).
  Web: `app/teach/layout.tsx` is the role gate — a server component that
  reads the signed-in user's `profiles.role` and `redirect()`s a
  non-teacher to `/dashboard`; `/teach` was also added to the middleware
  `PROTECTED_PREFIXES` so an unauthenticated visitor is sent to `/login`
  (defence in depth). `components/teach/teach-chrome.tsx` +
  `teach-rail.tsx` are the teacher chrome (top nav + a dedicated 72px
  rail — Home / Classes / Courses). `app/teach/page.tsx` is the teacher
  home: a compact dark command bar (greeting + Classes/Courses/Students/
  pending stat chips + New-class/New-course actions) over `Your classes`
  and `Your courses` sections — class cards (join-code pill, student
  count, coral "awaiting approval" strip) and course cards (status pill,
  unit/topic counts, published/draft split), each with a loading skeleton
  and an empty state. A `users` icon was added to the shared icon set.
  API: `GET /v1/teacher/classes` + `GET /v1/teacher/courses` added to
  `app/api/v1/teacher.py`, both `require_role('teacher','admin')` and
  scoped to the caller (`teacher_id` / `owner_id`); they return the
  teacher's classes (with active/pending student counts) and courses
  (with unit/topic/published/draft counts).
  >
  > **Verified.** `pnpm verify` → phase-1 17/17, phase-2 9/9, ALL CHECKS
  > PASS. `pnpm api:test` → 331 passed, 10 skipped (325 baseline + 6 new
  > teacher-list endpoint tests). Live, both roles: signed in as a
  > `student` (`/teach` → redirected to `/dashboard`); signed in as a
  > `teacher` (`/teach` renders — command bar + classes/courses sections
  > from the real endpoints, empty states for a teacher who owns none).
  > No migration. The `New class` / `New course` actions are visual only
  > — the create flows are tasks 3.2 / 3.3.

### [x] 3.2 — Class management + join approvals
- **Why:** teachers create classes, share codes, and approve students
  (the consent gate).
- **Build:** create class + join code; roster; **pending join requests
  with approve/remove**; `class_members` approve/remove endpoints + UI.
- **Acceptance criteria:** a teacher creates a class, sees a pending
  join, approves it (`status → active`, `approved_by/at` set), removes a
  student.
- **Verify:** `pnpm verify`; full join→approve loop with a test student.
- **Depends on:** 3.1.
- **Status:** done (2026-05-16).
  API: `app/api/v1/teacher.py` gained `POST /v1/teacher/classes` (create
  — mints a unique `PREFIX-XXXX` join code from an unambiguous alphabet),
  `GET /v1/teacher/classes/{id}` (roster + pending split + assigned
  courses; ownership-gated → 404 if not the caller's), `POST
  .../members/{sid}/approve` (the §14 consent checkpoint — sets
  `status='active'`, `approved_by`, `approved_at`) and `DELETE
  .../members/{sid}` (decline a pending / remove an active student). New
  `app/api/v1/classes.py` adds the student-side `POST /v1/classes/join`
  — redeem a code → idempotent `pending` membership.
  Web: `app/teach/classes/[id]/page.tsx` is the class detail screen — a
  dark command-bar header with a copyable join code, a coral-accented
  Pending-requests card with Approve/Decline, the active Roster with a
  confirm-gated Remove, and an Assigned-courses section; loading +
  not-found states. `components/teach/create-class-modal.tsx` is the
  New-class dialog (popped from `/teach`). `/teach` class cards now link
  through; the teacher chrome's breadcrumb + rail track the class route.
  >
  > **Verified.** `pnpm verify` → 17/17 + 9/9, ALL CHECKS PASS.
  > `pnpm api:test` → 345 passed, 10 skipped (331 baseline + 14 new tests
  > in `test_class_management.py`). Live full loop on the real DB: a
  > teacher created a class via the modal, two students joined by code
  > (`POST /v1/classes/join` → pending), the teacher saw both pending,
  > **approved** one (DB confirmed `status='active'` + `approved_by` +
  > `approved_at`), **declined** the other, and **removed** the approved
  > student from the roster. No migration.

### [x] 3.3 — Course/unit management + material upload
- **Why:** teachers need to create a course (subject, grade band,
  teaching style) and a unit, and upload material into it.
- **Build:** course/unit CRUD UI; the unit material upload UI calling
  `POST .../materials`.
- **Acceptance criteria:** a teacher creates a course with subject +
  grade band, a unit, and uploads the Fluids `.pptx`; it appears as a
  `lesson_materials` row.
- **Verify:** `pnpm verify`; upload the real deck through the UI.
- **Depends on:** 3.1, 2.1.
- **Status:** done (2026-05-16).
  Web: `components/teach/create-course-modal.tsx` (the New-course dialog
  — title/subject/grade band — popped from `/teach`),
  `app/teach/courses/[id]/page.tsx` (course detail — an editable
  teaching-style card + the units list + an inline add-unit form), and
  `app/teach/courses/[id]/units/[unitId]/page.tsx` (unit detail — a
  stage-then-upload material drop zone + the materials list with a
  conversion-status badge). All three are wired to the real endpoints
  via `lib/api.ts` + React Query (loading / not-found / error states).
  API: `app/api/v1/teacher.py` gained six endpoints, each
  `require_role('teacher','admin')` and ownership-gated explicitly (the
  service role bypasses RLS — a non-owned resource 404s, not 403s) —
  `POST /v1/teacher/courses` (creates an `origin='teacher'` course with
  a generated UNIQUE slug), `GET /v1/teacher/courses/{id}` (units +
  per-unit material counts + teaching style), `PATCH .../courses/{id}`
  (teaching style), `POST .../courses/{id}/units` (a unit at the next
  `n`), `GET /v1/teacher/units/{id}` (materials), and
  `POST /v1/teacher/units/{id}/materials` (multipart — pre-validates
  every file, then runs the task-2.1 `ingest_material` pipeline off the
  event loop via `to_thread`, rate-limited per teacher).
  >
  > DECISION: `POST .../materials` runs the §6 ingest (validate →
  > Storage → LibreOffice convert-to-PDF) SYNCHRONOUSLY. §6 principle 4's
  > async-`pipeline_jobs` rule targets the minutes-long *comprehension*
  > and *generation* stages (tasks 3.4 / 3.5); a single office-file
  > conversion is seconds, and §13 ("`segment` is rejected while
  > conversions are pending") confirms conversion completes before the
  > segment job runs. The 2.1 `ingest_material` building block is used
  > as built. `lesson_materials.kind` is left null at upload — §4 has it
  > model-proposed by later segmentation.
  >
  > **Verified.** `pnpm verify` → phase-1 17/17, phase-2 9/9, ALL CHECKS
  > PASS. `pnpm api:test` → 362 passed, 10 skipped (345 baseline + 17 new
  > tests in `test_course_management.py`). `tsc` clean; `next build` ok.
  > **Live end-to-end on the real cloud DB** (as a `teacher`-role
  > account): created a course (subject Physics, grade band 9-12) → a
  > unit → uploaded the real `Unit 8 - Fluids - AP Physics 1.pptx`
  > (4.9 MB) via `POST .../materials`; the ingest pipeline converted it
  > and wrote a `lesson_materials` row — `conversion_status='converted'`,
  > teacher-prefixed `storage_path`, `normalized_pdf` set (DB-confirmed).
  > **Live in the browser** (signed in as the teacher): the course page
  > rendered the real course (subject/grade, units list); the
  > teaching-style `PATCH` saved and re-displayed; the unit page showed
  > the uploaded deck with a "Ready" badge. Every acceptance criterion
  > met. A labeled `[3.3 verify]` course remains in the cloud DB as the
  > verification artifact (alongside the existing `e2e-fluids-demo`).
  > No migration, no web/API schema change. Next: 3.4.

### [x] 3.4 — Segmentation job UI + confirm-breakdown screen
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
- **Status:** done (2026-05-16).
  Web: the unit page gained a "Topic breakdown" section
  (`BreakdownPanel`) that drives off the unit's latest segment job —
  idle ("Generate breakdown" button — the explicit trigger), running (a
  converting → comprehending progress card; the unit query polls every
  2.5 s while a job is in flight), succeeded ("Review breakdown"), and
  failed (retry). New screen
  `app/teach/courses/[id]/units/[unitId]/breakdown/page.tsx` — the
  confirm checkpoint: a per-topic card editor (inline rename, expandable
  summary/key-points/pages, **split / merge-with-next / reorder / drop**),
  an **excluded-pages** panel with a per-row "re-include into [topic]"
  control, and a sticky Confirm bar. Edits are local React state, sent
  in the `POST .../topics` body on Confirm.
  API: `app/api/v1/teacher.py` gained `POST /v1/teacher/units/{id}/segment`
  (enqueues a `pipeline_jobs` `segment` row + runs it via
  `BackgroundTasks` → `jobs.run_job`; rejects 400 on no/unconverted
  material; returns an existing in-flight job rather than starting a
  second — §13; `ingest_acquire`-rate-limited), `GET .../units/{id}/
  segmentation` (the latest proposed breakdown + the `teach=false`
  excluded pages + the materials list), and `POST .../units/{id}/topics`
  (writes the edited topics onto the latest `unit_segmentations` row,
  `status='confirmed'`, then calls task-2.7's `confirm_breakdown`).
  `get_unit_detail` now also returns `segment_job`. The `segment` job's
  `comprehending` stage handler runs task-2.2's `segment_unit`;
  `converting` is an unregistered no-op (3.3 converts on upload).
  >
  > DECISION: the teacher's edits travel in the `POST .../topics` body
  > (client-side until Confirm) — the endpoint persists them onto the
  > `unit_segmentations` row first, so `confirm_breakdown` (which reads
  > the row) materialises the EDITED breakdown. No change to the 2.7
  > `confirm_breakdown` core. The segment job runs in-process via
  > FastAPI `BackgroundTasks` — fits this app's single-instance scale;
  > `run_job` is already resumable if the process restarts.
  >
  > **Verified.** `pnpm verify` → phase-1 17/17, phase-2 9/9, ALL CHECKS
  > PASS. `pnpm api:test` → 378 passed, 10 skipped (362 baseline + 16 new
  > tests in `test_segmentation.py`). `tsc` clean; `next build` ok.
  > **Live end-to-end on the real cloud DB**: enqueued a segment job on
  > the unit holding the real `Unit 8 - Fluids` deck → the job ran the
  > comprehension stage (~2 min, PRO model, 76 pages) → `succeeded` → the
  > model proposed **7 lesson-sized topics + 15 excluded pages**. Per the
  > 2026-05-16 granularity decision (see task 2.2) the doc's "~4"
  > estimate was the CED-grained guess; a 76-slide deck yields ~7-10
  > lesson-sized beats — accepted. **Edited** topic 1's title, confirmed
  > via `POST .../topics` → 7 `topics` rows (all `status='draft'`) + 61
  > `topic_pages` rows; the edit threaded through (DB-confirmed). **Live
  > in the browser** (signed in as the teacher): the unit page showed
  > "Breakdown ready", the breakdown screen rendered all 7 topics + 15
  > excluded pages + the editor controls, and clicking **Confirm**
  > re-confirmed idempotently (still 7 topics / 61 pages, not 14/122).
  > No migration. Next: 3.5.

### [x] 3.5 — Topic review/edit/preview + versions + publish
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
- **Status:** done (2026-05-16).
  Migration `supabase/migrations/20260516120000_topic_versions_validation.sql`
  — `topic_versions` gains a `validation jsonb` column (the §4 schema had
  no field for it; the publish gate needs per-version validation because
  the teacher can switch the live version). Applied to the cloud DB.
  Web: new screen `app/teach/courses/[id]/topics/[topicId]/page.tsx` —
  the single-scroll topic page: an editable design-notes card; a Lesson
  section that drives off the generate job (idle "Generate lesson" →
  rendering/generating/validating progress → done → failed); on done, a
  validation banner (validated / gap report), an inline per-step editor,
  "Preview as student" (→ the live `/classroom/{id}`) and "Re-generate";
  a Versions list (Live badge, per-version validation, make-live /
  delete); a sticky Publish bar, blocked until the active version
  validated. The unit page gained a "Topics" section linking into each
  topic page.
  API: `app/api/v1/teacher.py` — `GET /v1/teacher/topics/{id}` (lesson +
  versions + latest generate job), `PATCH .../topics/{id}` (design notes
  / hand-edited content — mirrored into the active `topic_versions` row,
  §6), `POST .../topics/{id}/generate` (a `generate` `pipeline_jobs` row
  run via `BackgroundTasks`; one-in-flight-per-topic; rate-limited),
  `POST .../versions/{vid}/activate`, `DELETE .../versions/{vid}` (400 on
  the active one), `POST .../topics/{id}/publish` (the §6 gate — 400
  unless the active version's `validation.passed` is true). The
  `generate` job's `rendering` stage runs task-2.3 `render_topic`,
  `generating` runs task-2.7 `generate_and_validate` and persists the
  `{passed,covered,total,gaps}` result onto the produced
  `topic_versions` row; `validating` is an unregistered no-op (validation
  runs inside `generate_and_validate`). `get_unit_detail` now also
  returns `topics`.
  >
  > DECISION: per-version validation is stored on the new
  > `topic_versions.validation` column — §4's schema omitted it, but
  > "publish blocked until validated" + "switches the live version"
  > together require the gate to read the ACTIVE version's status, not a
  > topic-wide or job-wide flag.
  >
  > **Verified.** `pnpm verify` → phase-1 17/17, phase-2 9/9, ALL CHECKS
  > PASS. `pnpm api:test` → 399 passed, 10 skipped (378 baseline + 21 new
  > tests in `test_topic_management.py`). `tsc` clean; `next build` ok.
  > **Live end-to-end on the real cloud DB** for the Fluids topic "States
  > of Matter & Fluids": publish-before-generation → 400 (gate blocked);
  > the `generate` job rendered + generated + validated → v1, 10 steps,
  > validated 3/3; a step `PATCH` persisted; **re-generate** → v2;
  > **activate** switched the live version back to v1; **publish** → 200
  > (DB-confirmed `status='published'`, 2 versions, active version
  > validated). **Live in the browser**: the topic page rendered the
  > PUBLISHED pill, the validation banner, 10 editable steps, the version
  > list (v1 Live / v2), the "Published" bar and the "Preview as student"
  > → `/classroom/{id}` link; the unit page's Topics section listed all
  > 7 topics with the published one marked.

### [x] 3.6 — Assign courses to classes
- **Why:** `class_courses` — the link that makes a teacher course
  visible to a class's students — had no writer. Phase 4 (the student
  dashboard, the classroom) READS it, but no teacher endpoint or UI
  ever created a row. Without this the teacher→student path is a dead
  end. (Added 2026-05-16 — gap found during task 4.1; §5 step 10 ties
  assignment to publishing but 3.2 / 3.5 did not build it.)
- **Build:** teacher endpoints to assign / unassign one of the
  teacher's courses to one of their classes (`POST` / `DELETE` on
  `class_courses`, §10); the class page's "Assigned courses" section
  becomes interactive — pick a course to assign, unassign an assigned
  one.
- **Acceptance criteria:** a teacher assigns one of their own courses
  to their own class → a `class_courses` row is created and the course
  appears in the class's "Assigned courses"; unassign removes it; a
  teacher cannot assign a class or a course that is not their own.
- **Verify:** `pnpm verify`; assign + unassign on the real DB; confirm
  an enrolled student's `GET /v1/me/courses` then reflects it.
- **Depends on:** 3.2, 3.5.
- **Status:** done (2026-05-16).
  API: two teacher/admin-gated endpoints on `app/api/v1/teacher.py` —
  `POST /v1/teacher/classes/{class_id}/courses` (`{course_id}` →
  201 `{id, title}`) and `DELETE /v1/teacher/classes/{class_id}/`
  `courses/{course_id}` (→ 204). Both `_load_owned_class` the class and
  (assign only) `_load_owned_course` the course, so a class or course
  the caller does not own 404s. Assign is idempotent — an existing
  `class_courses` row is not duplicated. `ClassCourseAssign` model added.
  Web: `app/teach/classes/[id]/page.tsx` — the static "Assigned courses"
  section became interactive: each assigned course has an unassign ×, and
  a `<select>` of the teacher's not-yet-assigned courses + "Assign"
  button creates the link (`assignMut` / `unassignMut`).
  Tests: `tests/test_class_courses.py` — 7 tests (assign creates row,
  idempotent, non-owned class 404, non-owned course 404, non-teacher 403,
  unassign 204, unassign non-owned class 404). Full API suite 411 passed.
  Verified each acceptance criterion: `pnpm verify` green; live on the
  cloud DB — assigned `e2e-fluids-demo` to class `a41be5bc…` (201, row
  created), re-POST stayed at one row (idempotent), the enrolled student's
  `GET /v1/me/courses` then showed it under `group='teacher'`, `DELETE`
  removed exactly that row (204) leaving the class's other assignment
  untouched; non-owned class/course 404 covered by unit tests.

---

# Phase 4 — Student side

> Section 4 is the student-facing surface for teacher content.
> (`teacher-authoring.md` §7, §8.)

### [x] 4.1 — Dashboard split
- **Why:** students must see Recommended vs From-your-teacher courses.
- **Build:** the dashboard course list split into the two groups;
  teacher group resolved via `class_members → class_courses`; the
  courses endpoint `group` field; "coming soon" for zero-published.
- **Acceptance criteria:** a student in a class sees its published
  teacher courses under "From your teacher"; an all-draft course shows
  "coming soon".
- **Verify:** `pnpm verify`; view the dashboard as an enrolled student.
- **Depends on:** 3.5.
- **Status:** done (2026-05-16).
  API: new `GET /v1/me/courses` (`app/api/v1/me.py`) — the dashboard
  course list, each item tagged `group` (`'recommended'` |
  `'teacher'`). Recommended = the built-in `origin='recommended'`
  courses; teacher = courses assigned (`class_courses`) to a class the
  caller is an **active** `class_members` member of, each carrying a
  `published_topic_count` so the dashboard can show "coming soon" for an
  all-draft course. `GET /v1/courses` (the public landing-page picker)
  was scoped to `origin='recommended'` so teacher courses never leak
  onto the marketing page; `GET /v1/courses/{slug}/units` now filters
  topics to `status='published'` so a teacher course's draft topics
  never show in a student's curriculum tree.
  Web: `app/(app)/dashboard/page.tsx` — the single "Your courses"
  section became two — **Recommended** and **From your teacher** (the
  latter rendered only when the student has ≥1 teacher course). A
  teacher course with `published_topic_count === 0` renders a "Coming
  soon" tag and is not enterable.
  >
  > GAP flagged: nothing yet WRITES `class_courses` — a teacher has no
  > endpoint/UI to assign a published course to a class. §5 step 10 ties
  > assignment to publishing; 3.2/3.5 did not build it and no task in
  > this plan owns it. The student side (4.1–4.3) READS `class_courses`;
  > it needs a teacher-side assign flow before the path is usable
  > end-to-end. Needs a home (a Phase 3 follow-up or a new task).
  >
  > **Verified.** `pnpm verify` → phase-1 17/17, phase-2 9/9, ALL CHECKS
  > PASS. `pnpm api:test` → 404 passed, 10 skipped (399 baseline + 5 new
  > tests in `test_my_courses.py`). `tsc` clean; `next build` ok.
  > **Live on the real cloud DB**: an enrolled student (`active` member
  > of a class with two teacher courses assigned — one with a published
  > topic, one all-draft) → `GET /v1/me/courses` returned 3 Recommended
  > + 2 teacher items, the published course `published_topic_count=1`,
  > the all-draft one `0`; a `pending` membership grants no teacher
  > course; `GET /v1/courses` excludes teacher courses. The dashboard's
  > "Recommended" section was confirmed rendering in the browser; the
  > "From your teacher" section is the same `SectHd` + `CourseCard` grid.
  > NOTE: a full browser-as-student render of the teacher section could
  > not be captured — admin-generated magic links produce implicit-flow
  > tokens the app's PKCE Supabase browser client does not consume, so a
  > fresh student session would not establish in the preview browser (an
  > environment limitation, not a 4.1 defect). No migration. Next: 4.2.

### [x] 4.2 — Join-a-class flow
- **Why:** students join a class with a code and wait for approval.
- **Build:** the "Join a class" action → `POST /v1/classes/join` →
  `pending` membership; "awaiting approval" state on the dashboard.
- **Acceptance criteria:** entering a valid code creates a `pending`
  row and shows "awaiting approval"; after teacher approval the class's
  courses appear; an invalid code errors cleanly.
- **Verify:** `pnpm verify`; join→approve→access end to end.
- **Depends on:** 4.1, 3.2.
- **Status:** done (2026-05-16).
  `POST /v1/classes/join` and the teacher approve/remove endpoints
  already existed (built earlier, tested in `test_class_management.py`),
  so 4.2 was the missing surfacing + UI.
  API: `GET /v1/me/courses` (`app/api/v1/me.py`) gained a third group —
  `'pending'`: a class the caller has a `pending` (not yet approved)
  `class_members` row for is returned as an item with `group='pending'`,
  `id` = class id, `title` = class name, no `slug`. The unapproved
  membership leaks no teacher course; the class itself shows so the
  dashboard can render "awaiting approval".
  Web: new `components/dashboard/join-class-modal.tsx` — a modal (the
  user-chosen pattern, mirrors `create-course-modal`) with a join-code
  field → `POST /v1/classes/join`; on success it invalidates
  `['dashboard-courses']` and shows a confirmation (pending → "request
  sent, awaiting approval"; already-active → "you're already in"). A
  404 maps to a friendly "couldn't find a class with that code". The
  dashboard's "From your teacher" section now renders **always** (so the
  "Join a class" button has a home), with an empty state when the
  student has no classes; a `group='pending'` item renders as a muted,
  non-enterable `PendingClassCard` ("Awaiting approval").
  Tests: `test_my_courses.py` — the old `ignores_pending_membership`
  test became `surfaces_pending_membership_as_awaiting_approval` (pending
  leaks no teacher course but surfaces as `group='pending'`), plus a new
  `pending_and_active_memberships_coexist`. File 5→6 tests; full API
  suite 411→412 passed.
  >
  > **Verified.** `pnpm verify` → typecheck/lint/build green, phases 1–2
  > all pass. `pnpm api:test` → 412 passed, 10 skipped. **Live on the
  > cloud DB** (join→approve→access end to end): the dev student
  > `POST /v1/classes/join` with class `a41be5bc`'s code → 200
  > `status=pending`; its `GET /v1/me/courses` then showed a
  > `group='pending'` "Period 6 — Physics Lab" item; an unknown code →
  > 404; the teacher's approve endpoint → 200; the student's
  > `GET /v1/me/courses` then showed the class's teacher course
  > (`group='teacher'`, no pending item); membership removed afterward.
  > **Browser** (signed in as a real student): the "From your teacher"
  > section showed the "Join a class" button + the pending "Awaiting
  > approval" card; the modal opened, an invalid code surfaced the
  > friendly error, a valid code showed the "request sent" panel; with
  > the membership flipped to `active` the dashboard showed the teacher
  > course card in place of the pending card. No console errors. No
  > migration. Next: 4.3.

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
