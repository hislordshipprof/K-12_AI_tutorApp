# CLAUDE.md — build rules for the teacher-authoring feature

## Source of truth — read these, in this order
1. `docs/teacher-authoring.md` — the architecture for the teacher-authored
   courses feature. Every schema, flow, endpoint, and edge case.
2. `docs/model-strategy.md` — which AI model powers which surface.
3. `docs/task-execution.md` — the **gated build checklist**. It defines
   the order of work and the acceptance criteria for every task.

These three are authoritative. If the code and a doc disagree, the doc
wins. If a doc is **ambiguous, missing, or self-contradictory — STOP and
ask the user.** Never guess and never invent a design that isn't written
down. A wrong guess that gets built is more expensive than a question.

## The execution rule — non-negotiable

- Work tasks **strictly in the order** `docs/task-execution.md` lists them.
- **NEVER start a task until the previous one is verified and its box is
  checked `[x]`.** One task `in progress` at a time.
- Before writing any code for a task, **state the WHY**: one or two
  sentences on why this task exists and what it unblocks. This goes in
  your response and keeps the work aligned to intent.
- Build **exactly** to the task's *Acceptance criteria* — no more (no
  speculative extras, no unrequested refactors), no less.
- When the build is done, run the task's *Verify* steps. Only when they
  **all pass** do you: tick the `[x]`, set *Status: done*, and move on.
- If verification fails, fix it. Do not proceed with a red check.
- If a task turns out to be wrong or blocked, stop and report — do not
  silently reshape it.

## Definition of done (every task)

A task is done only when ALL of:
- API touched → `cd apps/api && .venv/Scripts/pytest -q` passes, with
  **no fewer tests than the baseline** (169 at project start; the count
  only goes up).
- Web touched → `cd apps/web && npx tsc --noEmit` is clean AND
  `npx next build` succeeds.
- DB touched → a new timestamped migration in `supabase/migrations/`
  applies cleanly via `pnpm db:reset` and is idempotent.
- The task's own *Acceptance criteria* are demonstrably met (state how
  you verified each one).
- `pnpm verify` (the repo-wide gate) passes.

Never mark a task done on partial work, skipped tests, or a failing gate.

## Project conventions (match what exists — do not reinvent)

- Monorepo: **pnpm + turbo**. API = FastAPI (`apps/api`), Web = Next.js 15
  (`apps/web`, package `@edumind/web`).
- API endpoint → new file in `apps/api/app/api/v1/`, registered in
  `app/api/v1/router.py`. Settings/models live in `app/core/config.py`.
- Gemini access goes through `app/services/gemini.py`. Pin explicit model
  ids per `docs/model-strategy.md` §8 — no `*-latest` on generation paths.
- DB = Supabase. **Migrations only** — never edit an applied migration;
  add a new timestamped one. RLS on **every** new table.
- Web screens → `apps/web/src/app/.../page.tsx`; API calls via
  `apps/web/src/lib/api.ts`. Server-role key is **server-only**.
- Teacher/admin routes are role-gated. Demo-mode auth (`DEV_MODE` +
  `X-Dev-User-Id`) is being removed in Phase 0 — do not build new
  features on top of it.
- Don't add libraries, abstractions, or error handling the task doesn't
  need. Three similar lines beat a premature helper.

## Commits

- One commit per **verified, checked-off** task. The message references
  the task id (e.g. `feat(teacher): T-1.1 — schema migration`).
- Never commit secrets or `.env*` files.
- Create new commits; do not amend.

## When you finish a task

Report: what the WHY was, what you built, each acceptance criterion and
how it was verified, the test/build output, and the next task id. Then
wait for the gate to be confirmed before continuing.
