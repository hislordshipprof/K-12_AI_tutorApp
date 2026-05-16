# Teacher-authored courses — architecture & design

> Status: DESIGN — critiqued & build-ready. Last updated 2026-05-15.
> Decisions locked: class + join-code linking · join is **teacher-
> approved** · slides shown WITH Aria annotation · ingest PDF/Word/
> PowerPoint/plain-text · uploads normalised to PDF, read by a multimodal
> model for comprehension + rendered to page images · material uploaded
> per UNIT, model segments it into topics the teacher confirms · every
> upload takes ONE path (treated as unstructured — no fast-path branch) ·
> heavy stages run as async `pipeline_jobs` · teachers are invite-only ·
> real student auth replaces demo mode · re-generation keeps old versions
> (teacher picks the live one) and resets that topic's student progress ·
> Aria's persona is parameterised per course by subject + grade band +
> teaching style · compliance baseline built in Phase 0 (§14). Companion
> doc: `docs/model-strategy.md`.

## 1. Goal

Let a teacher upload their own lesson notes + slides, have Claude turn
them into Aria-narrated Socratic lessons in the teacher's chosen style,
and publish them to their students — alongside the existing built-in
("Recommended") AP courses.

Students see two course groups:
- **Recommended** — the current OpenStax-generated AP courses.
- **From your teacher** — courses a teacher published to a class the
  student has joined.

## 2. What we are NOT rebuilding

The `courses → units → topics.content → classroom → Aria` engine already
works — voice, word-timed captions, the scene/drawing system, quizzes.
Teacher courses are just `courses` rows with an owner. This project adds
**(a)** a new content *source* (teacher uploads instead of OpenStax) and
**(b)** a teacher-facing surface. Everything downstream is reused.

## 3. Concepts

| Concept | Meaning |
|---|---|
| Teacher | A `profiles` row with `role = 'teacher'`. Owns courses + classes. |
| Class | A teacher's section. Has a join code students enter once. |
| Recommended course | Built-in AP course (`origin = 'recommended'`, no owner). |
| Teacher course | A course a teacher owns (`origin = 'teacher'`, `owner_id` set). |
| Material | A file the teacher uploads for a unit — notes, a slide deck, a worksheet. One material often spans several topics. |
| Lesson | The generated `topics.content` Aria plays — same shape as today. |

## 4. Data model

Reuse the existing hierarchy; add ownership + a teacher layer. New
columns on existing tables:

```
profiles
  + role            text  not null default 'student'   -- 'student' | 'teacher' | 'admin'

courses
  + owner_id        uuid  references profiles(id)        -- null = Recommended
  + origin          text  not null default 'recommended' -- 'recommended' | 'teacher'
  + subject         text                                 -- 'Physics'|'Biology'|'Reading'|…
  + grade_band      text                                 -- 'K-2'|'3-5'|'6-8'|'9-12'
  + teaching_style  text                                 -- teacher's "how I teach" voice
  (the existing `courses` table has NO `subject` column today — this
   adds it. subject + grade_band + teaching_style parameterise Aria's
   persona at generation time — see §6 "Persona". All three are null on
   Recommended courses, which keep the built-in physics persona.)

topics
  + status            text  not null default 'published' -- 'draft' | 'published'
  + design_notes      text                               -- per-lesson teacher guidance
  + active_version_id uuid  references topic_versions(id) -- the live generated lesson
  + quiz_source       text  not null default 'auto'      -- 'auto' | 'practice'
  (a topic's source pages live in the `topic_pages` join table — a topic
   may legitimately draw pages from MORE THAN ONE material (slides + a
   notes doc), so a single FK + int[] cannot represent it.
   `content` jsonb still holds the *live* generated lesson — a mirror of
   the active version — so the classroom loader is unchanged.
   INVARIANT: `topics.content` == `topic_versions[active_version_id].content`.
   `content_provenance` records that it was teacher-generated.
   For teacher courses, topic rows are CREATED by segmentation — see §6 —
   not pre-authored by the teacher.)

topic_progress
  + active_version_id uuid references topic_versions(id) -- the lesson
                       -- version this progress was made against (see
                       -- "Progress & re-generation"). Null for
                       -- Recommended-course progress.

quiz_questions
  + topic_version_id  uuid references topic_versions(id) -- the lesson
                       -- version this question set belongs to. Null on
                       -- Recommended courses (topic-scoped, as today);
                       -- set for teacher courses so quizzes version with
                       -- the lesson. The live quiz = rows whose
                       -- topic_version_id = topics.active_version_id.
```

New tables:

```
classes
  id           uuid pk
  teacher_id   uuid references profiles(id)
  name         text
  subject      text                       -- 'Physics', 'Biology', …
  join_code    text unique                -- short code, e.g. "PHYS-7K2Q"
  archived     bool default false
  created_at   timestamptz

class_members                              -- a student belongs to a class
  class_id     uuid references classes(id)
  student_id   uuid references profiles(id)
  status       text  not null default 'pending' -- 'pending' | 'active'
  requested_at timestamptz                      -- when the student entered the code
  approved_by  uuid references profiles(id)     -- teacher who admitted them
  approved_at  timestamptz                      -- the school-mediated consent record
  primary key (class_id, student_id)
  -- a student gains access only once the teacher approves (status='active');
  -- approval is the logged consent checkpoint — see §14.

class_courses                              -- which teacher courses a class sees
  class_id     uuid references classes(id)
  course_id    uuid references courses(id)
  assigned_at  timestamptz
  primary key (class_id, course_id)

lesson_materials                           -- the teacher's raw uploads
  id                uuid pk
  unit_id           uuid references units(id)  -- uploaded at the UNIT level —
                                               -- one material may cover many topics
  kind              text   -- 'notes' | 'slides' | 'practice'
                            --  (model-proposed, teacher-editable)
  storage_path      text   -- original upload (Supabase Storage key)
  normalized_pdf    text   -- the upload converted to PDF (universal form)
  filename          text
  mime              text
  conversion_status text   -- 'pending' | 'converting' | 'converted' | 'failed'
                            --  (PDF conversion only — page rendering is a
                            --   separate post-confirm step, see §6)
  uploaded_by       uuid references profiles(id)
  uploaded_at       timestamptz
  -- the model's READ of the material is unit-level (it fuses every file
  -- in the unit) and lives in `unit_segmentations`, not on this row.

material_pages                             -- one rendered page image per DISPLAYED page
  material_id  uuid references lesson_materials(id)
  idx          int             -- page order within the material
  image_path   text            -- Supabase Storage PNG
  primary key (material_id, idx)
  -- a topic claims a subset of these via the `topic_pages` join table.
  -- only pages that will be SHOWN are rendered — comprehension reads the
  -- PDF directly, so prose notes / practice pages are never rasterised
  -- (see §6 render track).

unit_segmentations                         -- unit-level comprehension + breakdown
  id             uuid pk
  unit_id        uuid references units(id)
  comprehension  jsonb   -- the model's combined multimodal read of ALL the
                         -- unit's materials — per-section key points,
                         -- per-figure descriptions, per-material kind, and
                         -- per-page teach/skip classification
  proposed       jsonb   -- proposed topic breakdown: list of {title, summary,
                         -- page set, practice-question→topic tags}
  status         text    -- 'proposed' | 'confirmed'
  created_at     timestamptz
  -- re-segmenting a unit appends a new row; the latest drives the confirm
  -- UI. Segmentation is a UNIT artifact — it cannot live on one material.

topic_pages                                -- which rendered pages a topic uses
  id           uuid pk
  topic_id     uuid references topics(id)
  material_id  uuid references lesson_materials(id)
  page_idx     int                  -- → material_pages(material_id, idx)
  role         text                 -- 'slide' | 'figure' (notes/practice
                                     --  are never rendered, so never here)
  ord          int                  -- display order within the topic
  unique (topic_id, material_id, page_idx)
  -- replaces the old single-FK topics.source_material/source_pages so a
  -- topic can span pages from several materials. A generated step
  -- references a row by its stable `id` (see §6 step shape).
  -- IMMUTABLE per topic: the page set is fixed at breakdown-confirm.
  -- Re-generating a topic re-writes narration but never the page set,
  -- so every topic_versions row's step→page ids stay valid.

topic_versions                             -- generated-lesson history
  id           uuid pk
  topic_id     uuid references topics(id)
  content      jsonb           -- a full generated lesson (today's step shape)
  label        text            -- "v1", "v2 — added Bernoulli example", …
  created_at   timestamptz
  created_by   uuid references profiles(id)
  -- re-generating a topic appends a new row; topics.active_version_id
  -- points at the live one and topics.content mirrors it. The teacher
  -- can switch the active version or delete an old (non-active) row.

teacher_invites                            -- invite-only teacher onboarding
  code         text primary key            -- redeemable invite code
  created_by   uuid references profiles(id)
  redeemed_by  uuid references profiles(id) -- null until used
  redeemed_at  timestamptz
  created_at   timestamptz
  -- an admin issues a code; the teacher redeems it at sign-up and
  -- their profile is set role = 'teacher'.

pipeline_jobs                              -- async work — see §6
  id           uuid pk
  kind         text   -- 'segment' | 'generate'
  unit_id      uuid references units(id)   -- set for 'segment'
  topic_id     uuid references topics(id)  -- set for 'generate'
  status       text   -- 'queued' | 'running' | 'succeeded' | 'failed'
  stage        text   -- progress within the job:
                       --  segment job:  'converting' | 'comprehending'
                       --  generate job: 'rendering' | 'generating' | 'validating'
  error        text                        -- failure detail, null on success
  created_at   timestamptz
  updated_at   timestamptz
  -- comprehension + generation take minutes; they CANNOT run inside the
  -- HTTP request. The API enqueues a job and the board polls its status.
```

A teacher course still flows through `units` and `topics` exactly like a
Recommended course, so the classroom needs no change to *load* it.

### RLS (defense-in-depth — schema sketch)
- `classes` / `class_courses`: teacher rows where `teacher_id = auth.uid()`.
- `lesson_materials` / `material_pages` / `unit_segmentations` /
  `topic_pages` / `pipeline_jobs`: these have no `teacher_id` column —
  RLS reaches the teacher by joining up to `courses.owner_id`
  (`unit_id → units → courses`, or `topic_id → topics → units → courses`
  for `generate` jobs). Implement the join once as a SQL helper function
  and reuse it across the policies.
- `class_members`: a student can insert their *own* row via a valid join
  code (it lands `status = 'pending'`); read their own memberships. Only
  the class's teacher may flip a row to `status = 'active'`.
- `topics` of teacher courses: a student may read a topic only if
  `status = 'published'` AND the course is in a `class_courses` row for a
  class the student is an **`active`** member of.

### Progress & re-generation
Student `topic_progress` / `lesson_sessions` are keyed by step index, so
a re-generated lesson (different step count) would mis-map them. Rule:
`topic_progress` carries the `active_version_id` it was made against;
when a teacher publishes a *new* active version, that one topic's
progress is reset for the class's students and they see a "lesson
updated" notice. Other topics are untouched. Quiz attempts version the
same way — `quiz_questions` is version-scoped (§6 "Quiz"), so old
`quiz_attempts` stay bound to the version the student actually took.

### Enrollment for teacher courses
A student reaches a teacher course through `class_members → class_courses`
— that is the access-control path, enforced by RLS. So a student
**cannot enrol in, or even read the content of, a teacher course until
the teacher has approved their class join** (`class_members.status =
'active'`). Approval is granted once per *class*, not per course — after
that, every course assigned to the class is immediately available.
Recommended courses are unaffected: they have no class and students
self-enrol as today.

The first time a student opens a teacher course, the system inserts an
`enrollments` row — the existing "this user is taking this course"
record the dashboard, progress, and history already rely on. Enrollment
is NOT authorization: it is created lazily *after* access is already
granted, and a stale enrollment after a course is un-assigned is
harmless because RLS still gates access. (The course appears in the
dashboard's "From your teacher" group as soon as it is assigned —
resolved via `class_courses`, before any enrollment row exists.)
Reusing `enrollments` means every existing student-side query works
unchanged.

## 5. Teacher authoring flow

A single upload often covers a whole unit — many topics. Teachers
organise by unit, not by our DB's topic rows, so they upload at the
unit level and the system discovers the topics inside.

1. Teacher opens the admin board (`/teach`), role-gated.
2. Creates a **class** → gets a join code to share with students.
3. Creates a **course** — subject, title, and **grade band** (subject +
   grade band parameterise Aria's persona for every lesson in the
   course, §6 "Persona") — and a **unit**.
4. Sets the course's **teaching style** once ("how I teach": the
   questions I ask, how I scaffold, my tone).
5. **Uploads the unit's material** — one or more files (notes, slide
   decks, worksheets). No need to pre-chop it per topic.
6. Uploading kicks off an async **segmentation job** (§6) — convert,
   render, comprehend. The board polls and shows job progress; when it
   finishes the model has **proposed a topic breakdown** ("this unit =
   topics A, B, C with these page sets").
7. **Teacher confirms the breakdown** — rename / merge / split / reorder
   / drop proposed topics, AND re-include any teaching page the model
   wrongly excluded (excluded pages are *shown*, not hidden). This is
   the key human checkpoint: the model proposes, the teacher disposes.
8. On confirm, a `topics` row + its `topic_pages` are created per topic,
   and a per-topic **generation job** runs (§6) → draft `topics.content`.
9. **Reviews / edits** the generated steps per topic in the board, and
   can preview the lesson as a student would see it before publishing.
10. **Publishes** (`status = 'published'`) → assigns the course to one
    or more classes (`class_courses`).

## 6. Generation pipeline (teacher source)

A sibling of the existing OpenStax pipeline. Same destination
(`topics.content`), different source.

```
SEGMENT job (one per unit):
  upload → ingest → normalize → comprehend + segment → proposed breakdown
                                                              │
                                                    teacher confirms
                                                              │
GENERATE job (one per confirmed topic):
  render claimed pages → generate lesson + scenes → validate → draft
                                                              │
                                                  teacher reviews → publish
```

Three principles drive this:
1. **A model comprehends a document; it cannot hand back the asset files
   inside it.** Comprehension (understanding the content) and rendering
   (producing the slide images we display) are separate concerns —
   comprehension runs in the segment job; rendering runs in the
   per-topic generate job, over only the pages that topic shows.
2. **One upload usually spans several topics.** The comprehension step
   also *segments* — turning an unstructured document into a proposed
   topic structure the teacher then confirms.
3. **Every upload takes exactly ONE path — treated as unstructured.**
   There is no structured-vs-unstructured fast-path branch. A neatly
   numbered deck and a wall of unlabelled notes both go through the
   *same* comprehend + segment + teacher-confirm flow. Structure in the
   source is not skipped over — it just makes the model's proposed
   breakdown more accurate (a deck with explicit "8.1 / 8.2 / 8.3"
   headings yields proposals the teacher mostly accepts as-is; messy
   notes yield proposals the teacher edits more). One code path, no
   format detection, no two-mode logic to keep correct.
4. **Both heavy stages run as async jobs.** The segment job (ingest +
   convert + comprehend + segment) and each per-topic generate job
   (render + generate + validate) take minutes — far past any HTTP
   timeout. The API enqueues a `pipeline_jobs` row; a background worker
   runs it; the board polls the job's `status` / `stage`. No pipeline
   work runs inside a request handler. Stages are idempotent and
   resumable — a job that fails at `comprehending` does not re-do
   conversion on retry.

- **Ingest (validate first).** Teacher uploads are *untrusted files*.
  Before anything else: enforce a per-file size cap, allow-list MIME
  types (PDF / Word / PowerPoint / plain text) and reject spoofed or
  mismatched types, and run the LibreOffice conversion **sandboxed** —
  resource-limited, no network. Teacher pipeline calls (upload, segment,
  generate) are rate-limited and quota-capped per teacher so a runaway
  upload loop cannot burn the model budget.

- **Normalize → PDF.** Every upload becomes a PDF — the universal
  intermediate that the comprehension model reads AND that we render to
  images. No per-format branching downstream.
  - PDF → used as-is.
  - Word `.docx`, PowerPoint `.pptx` → converted to PDF via a
    server-side LibreOffice headless step (a Docker layer on the API).
  - Plain text / paste → wrapped into a PDF.

- **Comprehend + segment (model track).** All of the unit's uploads are
  combined and handed to Gemini as one multimodal input. The model
  *reads the whole document* — prose, tables, equations, figures — far
  better than mechanical scraping (handles scanned pages, handwriting,
  messy layout). It writes a `unit_segmentations` row:
  - per-section key points + per-figure descriptions;
  - a **proposed topic breakdown** — a list of distinct topics, each
    with a title, summary, and the page set that covers it;
  - per-material kind (`notes` / `slides` / `practice`), per-page
    teach/skip classification, a flag on any section too thin to teach;
  - for `practice` material, **each question tagged with the topic it
    assesses** — so a topic that opts into `quiz_source = 'practice'`
    knows which questions are its own.
  Comprehension is a one-shot, quality-critical call — it runs on a
  stronger model than the per-step work (see `docs/model-strategy.md`
  §6). The size ceiling is the *combined* slides+notes+practice payload,
  not page count alone — chunk above a token threshold (§13).
  The teacher confirms/edits this breakdown (§5.7) before generation.

- **Render (asset track).** Rendering exists ONLY to *display* the
  teacher's slides/figures in the classroom — comprehension reads the
  PDF directly, and the model can describe a diagram but cannot return
  its pixels. So `pymupdf` rasterises to PNG (`material_pages`) only the
  pages that will be shown — `slides` and figure-bearing pages, never
  prose `notes` or `practice` worksheets. Rendering is deferred until
  after the breakdown is confirmed and runs only for pages a
  `topic_pages` row actually claims (a topic may pull pages from more
  than one material).

- **Generate (per confirmed topic).** For each topic the teacher
  confirmed, the model writes the Aria lesson from that topic's slice of
  the `comprehension` JSON + the topic's `design_notes`. **Aria's
  persona is parameterised** — built per course from `courses.subject`,
  `courses.grade_band`, and `courses.teaching_style`, NOT the hard-coded
  physics persona (see "Persona" below). **Depth scales with the
  material** — the fixed 8-step rubric is dropped; a lesson is as long
  as the content needs. Each step maps to the page it covers, and the
  generate job **also assigns each step a `scene`** — reusing the
  existing scene system (typed registry first, Claude-authored fallback
  for steps no typed scene fits). Scene assignment runs inside the same
  `pipeline_jobs` 'generate' job, so a finished topic already has its
  drawings — there is no separate offline scene script for teacher
  courses.

- **Quiz.** Each teacher topic still ends with a quiz. Two sources, the
  teacher's choice per topic:
  - *Auto-generated from the lesson* (default) — the existing quiz
    generator, run against the topic's `comprehension` slice. Zero extra
    teacher work; consistent with Recommended courses.
  - *From the teacher's practice material* — if the unit upload included
    material classified `practice` (worksheets), the teacher can build
    the quiz from those questions instead, so it matches their real
    assessments.
  A `topics.quiz_source` field (`'auto' | 'practice'`) records the
  choice. Quizzes live in the existing separate `quiz_questions` table,
  NOT inside `topics.content` — so to version with the lesson,
  `quiz_questions` gains a `topic_version_id` (§4): each generate job
  writes a fresh question set tagged to the version it produced, and the
  live quiz is the set whose `topic_version_id` = the topic's
  `active_version_id`. Past `quiz_attempts` therefore stay bound to the
  version the student actually took. `quiz_source = 'practice'` is
  selectable only when the unit has `practice` material with questions
  tagged to that topic — otherwise the field is forced to `'auto'`.

- **Validate.** Check the lesson actually covers the teacher's key
  points (the existing validator pattern, run against the
  `comprehension` output instead of OpenStax). On failure the
  generation job retries once; a second failure leaves the topic in
  `draft` with the validator's gap report surfaced in the board — the
  teacher adds `design_notes` and re-generates. **Publish is blocked
  until a topic's lesson validates.**

- **Review.** Teacher edits in the board — and can preview the lesson
  as a student would experience it — before publishing. Hand-edits
  mutate the active version's `content` in place (they do not spawn a
  new `topic_versions` row; only a re-generate does).

Each generated step keeps today's shape and gains an optional page
reference:

```
{ tts, html, dur, scene, page? }
```

`page` is the `id` of a `topic_pages` row — i.e. *which* of the topic's
claimed pages this step is taught over. Steps with no `page` fall back
to the chalkboard (§7).

> **Persona.** Recommended (OpenStax) courses keep the built-in
> physics-tutor persona. Teacher courses do NOT — at generation time
> Aria is assembled from the course's `subject`, `grade_band`, and
> `teaching_style`. A K-2 reading lesson gets short sentences, simple
> words and gentle pacing; an AP physics lesson gets domain vocabulary
> and rigour. `teaching_style` layers on the teacher's voice but is
> ADDITIVE — it never overrides the core Socratic rules (never give the
> answer outright, one idea per step). `apps/api/app/agents/prompts.py`
> today hard-codes the physics persona; it must become a builder keyed
> on subject + grade band.

> **On animations.** PowerPoint builds/transitions are playback
> instructions, not content — they do not transfer and are not a goal.
> Authors also fake builds by *duplicating a slide* and adding one
> element per copy (real example: the Fluids deck repeats "Solid" across
> slides 6–8 and "Density" across 14–16). Both forms — true transitions
> and duplicate-slide builds — are collapsed: we keep each beat's *final
> state* only. The "build-up" pacing is recreated natively by Aria's
> word-timed narration and live scene annotation, synced to her voice.
> That replaces slide animation with something better.

## 7. Slides + annotation in the classroom

Decision: show the teacher's slides AND let Aria annotate on top.

The scene system already overlays SVG drawings on the chalkboard. For a
teacher lesson step that has a `page`, the classroom renders:

```
[ slide image (the topic_pages row that step.page points at) ]  ← backdrop
[ scene SVG overlay — Aria's annotations  ]                      ← existing scene engine
[ word-timed caption                      ]                      ← existing
```

So "slides + annotation" reuses the scene engine unchanged — it just
draws over a slide image instead of the dark board. Steps with no
`page` fall back to the normal chalkboard.

## 8. Student experience

- **Dashboard** — the course list splits into **Recommended** and
  **From your teacher** (the latter resolved via the student's
  `class_members` → `class_courses`).
- **Join a class** — a "Join a class" action takes a join code →
  inserts a `pending` `class_members` row. The student gets access only
  once the teacher approves them (§9); until then the class shows as
  "awaiting approval".
- **Classroom** — unchanged except it now also renders slide-backed
  steps (§7). Opening a teacher course for the first time auto-creates
  an `enrollments` row, so progress / history work exactly as for
  Recommended courses (§4 "Enrollment for teacher courses").

## 9. Admin board (`/teach`, role-gated)

| Page | Purpose |
|---|---|
| `/teach` | Teacher home — classes + courses overview |
| `/teach/classes/[id]` | Roster, **pending join requests to approve**, join code, assigned courses |
| `/teach/courses/[id]` | Units tree; course teaching-style |
| `/teach/courses/[id]/units/[id]` | Upload unit material → watch the segmentation job → review the proposed breakdown (incl. **excluded pages**) → confirm |
| `/teach/courses/[id]/topics/[id]` | Per-topic design notes, watch the generation job, review/edit/preview generated steps, Publish |

A pipeline job that finishes while the teacher is away surfaces as a
**badge** on `/teach` (and the relevant course/unit row) — the teacher
does not have to sit on the page polling for a minutes-long job.

## 10. API surface (new)

Role-gated under `/v1/teacher/*`:
- `classes` — create / list / roster / regenerate join code
- `class_members` — list pending join requests, approve, remove a student
- `courses` / `units` — CRUD
- `POST /v1/teacher/units/{id}/materials` — upload one or more files
- `POST /v1/teacher/units/{id}/segment` — enqueue a segmentation job →
  returns a `job_id`
- `GET  /v1/teacher/units/{id}/segmentation` — the latest proposed
  breakdown (incl. excluded pages) once the segmentation job finished
- `POST /v1/teacher/units/{id}/topics` — confirm the breakdown → create
  the `topics` rows + their `topic_pages`
- `POST /v1/teacher/topics/{id}/generate` — enqueue a generation job →
  returns a `job_id` (on success appends a `topic_versions` row, active)
- `GET  /v1/teacher/jobs/{id}` — poll a `pipeline_jobs` status / stage
- `GET  /v1/teacher/topics/{id}/versions` — list versions
- `POST /v1/teacher/topics/{id}/versions/{vid}/activate` — make a version live
- `DELETE /v1/teacher/topics/{id}/versions/{vid}` — delete a non-active version
- `POST /v1/teacher/topics/{id}/publish`

Onboarding:
- `POST /v1/admin/teacher-invites` — admin issues an invite code
- `POST /v1/auth/redeem-teacher-invite` — teacher redeems a code at
  sign-up → profile gets `role = 'teacher'`

Student-facing:
- student auth (sign-up / sign-in) — real Supabase accounts, replacing
  demo mode
- `POST /v1/classes/join` — redeem a join code → creates a `pending`
  membership that awaits teacher approval
- `GET  /v1/topics/{id}/slide/{topic_page_id}` — short-lived signed URL
  for a slide image, gated on `active` membership of a class the
  course is assigned to
- the dashboard courses endpoint gains a `group` field
  (`recommended` | `teacher`) and surfaces `pending` memberships as
  "awaiting approval"

Storage: a Supabase Storage bucket `lesson-materials`; teachers write to
their own prefix; the pipeline reads via the service role. Students
never get bucket access directly — the classroom requests slide images
through the API, which mints **short-lived signed URLs**, and only for
pages of topics in a course the student is an `active` member of.

## 11. Open questions / risks

1. **Becoming a teacher** — RESOLVED: invite-only via an invite-code
   flow. An admin issues a code (`teacher_invites`); the teacher redeems
   it at sign-up and their profile is set `role = 'teacher'`. Not
   self-serve.
2. **Document conversion** — RESOLVED (§6): all uploads normalise to PDF,
   then a multimodal model comprehends them and `pymupdf` renders page
   images. **LibreOffice headless** (Word/PowerPoint → PDF) ships as a
   Docker layer on the API image in Phase 2 — `.docx` / `.pptx` are
   supported from day one, no PDF-only interim.
3. **Re-generation / versioning** — RESOLVED: keep versions. Each
   re-generation appends a `topic_versions` row; the teacher picks which
   version is live (`topics.active_version_id`) and can delete old,
   non-active versions. No silent overwrite.
4. **Upload granularity** — RESOLVED (§5, §6): material is uploaded at
   the *unit* level; one upload may cover several topics. The
   comprehension step segments it into a proposed topic breakdown the
   teacher confirms. Course-level upload (one doc → a whole course) is a
   later enhancement.
5. **Very large uploads** — a whole unit may be a 100+ page deck. Gemini's
   long context handles most, but cost/latency rise. May need chunked
   comprehension above a *token* threshold on the combined payload
   (see §13).
6. **Quiz source** — RESOLVED (§6): each teacher topic ends with a quiz;
   default is auto-generated from the lesson, but if the upload included
   `practice` material the teacher can build the quiz from that instead.
   `topics.quiz_source` records the choice.
7. **Student identity** — RESOLVED: real student accounts. The current
   demo-mode single-user shortcut is replaced by genuine Supabase auth
   for students (sign-up / sign-in), so each student is a distinct
   `profiles` row that joins classes and owns its own progress. This is
   a prerequisite for classes to be real — built in Phase 0.
8. **Class join control** — RESOLVED: teacher-approved. A join code
   creates a `pending` `class_members` row; the teacher admits each
   student from the roster. No student lands in a class unseen — the
   approval doubles as the school-mediated consent checkpoint (§14).
9. **In-flight progress on re-generation** — RESOLVED (§4 "Progress &
   re-generation"): publishing a new active version resets that one
   topic's progress for the class's students, with a notice.
10. **Pipeline is long-running** — RESOLVED (§6 principle 4):
    segmentation and per-topic generation run as async `pipeline_jobs`
    with a polled status — never inside an HTTP request handler.
11. **Compliance** — RESOLVED for v1 baseline (§14); verifiable
    parental consent + per-school data-processing agreements remain
    pre-launch legal work, tracked there.
12. **Subject & grade scope** — RESOLVED: teacher courses are subject-
    and grade-aware from v1. Aria's persona is parameterised by
    `courses.subject` + `courses.grade_band` + `courses.teaching_style`
    (§6 "Persona"); `prompts.py` becomes a persona *builder* instead of
    a hard-coded physics tutor.
13. **Teacher pipeline cost / abuse** — RESOLVED (§6 "Ingest"): per-file
    size caps, per-teacher rate limits and quotas bound the expensive
    multimodal / Pro calls.
14. **Quiz versioning** — RESOLVED: quizzes live in the separate
    `quiz_questions` table (not in `content`); it gains a
    `topic_version_id` so a quiz versions with its lesson (§6 "Quiz").
15. **Enrollments** — RESOLVED: opening a teacher course auto-creates an
    `enrollments` row so existing dashboard / progress / history logic
    is reused unchanged. Access control stays with `class_members` + RLS
    (§4 "Enrollment for teacher courses").
16. **Admin role** — RESOLVED: `profiles.role` gains `'admin'`; only an
    admin may issue `teacher_invites`.

## 12. Phased delivery plan

0. **Auth & compliance foundation** — replace demo mode with real
   Supabase auth. This touches *every existing endpoint* (they all use
   the demo user / `X-Dev-User-Id`) so it is its own phase, not a
   side-task inside "Foundations". Includes the `teacher_invites`
   redeem-at-sign-up flow, the teacher-approves-join consent gate, and
   the §14 compliance baseline. Shippable as "the app has real accounts".
1. **Schema foundations** — migration (the §4 schema),
   `lesson-materials` Storage bucket, RLS, the `role` check helper, and
   the `pipeline_jobs` async-worker harness. No teacher UI yet.
2. **Authoring pipeline** — ingest validation, normalize-to-PDF
   (LibreOffice headless Docker layer), multimodal comprehension +
   **topic segmentation**, slide rendering (`pymupdf`), the
   subject/grade **persona builder**, depth-scaled generation with
   scene assignment, quiz generation (auto + practice-material),
   validator — all driven through `pipeline_jobs`. Proven via a script
   on one real unit upload.
3. **Admin board** — the `/teach` pages (§9): job-progress polling, the
   confirm-the-breakdown screen (with excluded pages), per-topic
   review/preview.
4. **Student side** — dashboard split, class join + awaiting-approval
   state, classroom slide+annotation rendering (§7).
5. **Polish** — re-generation / version UX, course cover art, analytics.

Each phase is independently shippable and verifiable.

## 13. Edge cases & how we handle them

Teachers build materials every which way. The segmentation step turns an
unstructured document into structured topics — these are the cases it
must survive. The recurring safety net is the **teacher-confirms-the-
breakdown** checkpoint (§5.7): the model only ever *proposes*.

| Case | Handling |
|---|---|
| One file spans many topics / many files = one topic | Segmentation runs over the unit's **combined** material, not per-file. |
| Title / agenda / "any questions?" / reference pages | Model classifies non-teaching pages and excludes them — they never become a topic. |
| Recap or review slides repeating earlier content | Segmentation must not spawn a duplicate topic from a recap; flag near-duplicate sections. |
| Consecutive near-duplicate slides from animation builds (same title, progressively more content — e.g. a deck with slides 6/7/8 all "Solid", 14/15/16 all "Density") | These are ONE teaching beat authored as a slide-by-slide build, not three topics or three steps. Comprehension collapses a run of near-identical consecutive slides into a single beat and keeps only the **final** (most complete) slide as the rendered page; the earlier partial frames are dropped. Aria recreates the build-up natively via word-timed narration + scene annotation (§6 "On animations"). |
| Over- / under-splitting (blurred boundaries) | Teacher confirm step can merge / split / add / drop proposed topics. |
| Model wrongly excludes a real teaching slide as "agenda"/non-teaching | The confirm screen **shows excluded pages**, not just kept ones, with a one-click re-include — a wrong exclusion is visible and recoverable, never silent. |
| Thin / sparse material (a few bullet words) | Quality gate: the model flags a section as "too thin to teach"; the board asks the teacher to add notes rather than generate a hollow, hallucination-prone lesson. |
| Slides + a separate notes doc for the same unit | Combined comprehension fuses them — notes add depth, slides add visuals; they need not align 1:1. A topic spans both via `topic_pages`. |
| Worksheets / practice mixed in with teaching material | Classified `practice`, never turned into a lesson. Comprehension tags each practice question with the topic it assesses, so a topic with `quiz_source = 'practice'` can draw its own questions. |
| Non-contiguous coverage (covers A, then B, then back to A) | Comprehension maps concept→pages; `topic_pages` is a page **set** that may span several materials, not a single range. |
| Teacher's unit names don't match AP CED | Fine — teacher courses have their own unit tree (`owner_id`); no forced alignment. |
| Re-upload of revised material | Re-segment proposes a fresh breakdown; teacher re-confirms. Re-generating a topic appends a `topic_versions` row — the prior version is preserved, not overwritten; the teacher chooses the live one and can delete old versions. |
| Re-segmenting a unit that already has PUBLISHED topics | Re-segmentation only *proposes* and diffs against existing topics — it never auto-deletes. The teacher maps proposed→existing (keep / replace / add / retire). Replacing a topic follows the §4 progress-reset rule; retiring one hides it from new students while in-progress students keep it. |
| Teacher double-submits the confirm-breakdown step | `POST .../topics` is idempotent — repeating a confirm of the same breakdown does not create duplicate topic rows. |
| Two uploads / segment jobs race on one unit | At most one in-flight segmentation job per unit — a new request while one is `running` is queued, never run concurrently. |
| Two generate jobs for the same topic | At most one in-flight generate job per topic — same rule as the per-unit segment job. |
| `segment` called before materials finish converting | The segment job requires every material at `conversion_status = 'converted'`; a call with no materials, or while conversions are pending, is rejected. |
| Malicious / corrupt / spoofed upload | Rejected at ingest (§6) — size cap, MIME allow-list, sandboxed conversion. A file that fails conversion marks `conversion_status = 'failed'` and surfaces to the teacher; it never reaches comprehension. |
| Upload has no teachable content (a grade spreadsheet, a permission slip) | Comprehension returns an empty breakdown with a reason; the board says "nothing teachable found here" rather than inventing hollow topics. |
| Lesson generation fails validation | The generation job retries once; a second failure leaves the topic `draft` with the validator's gap report shown. Publish is blocked until it validates. |
| Pipeline crashes mid-run (conversion ok, comprehension dies) | Stages are idempotent and keyed to the material/unit; the job resumes from the failed `stage` rather than re-doing completed work. |
| Course un-assigned from a class while a student is mid-lesson | RLS revokes on `class_courses` delete. v1: the student keeps any topic already `in_progress`/`done`; only un-started topics disappear — no hard mid-lesson cut-off. |
| Teacher course assigned to a class with zero published topics | Shows on the student dashboard as "coming soon"; not enterable until it has ≥1 `published` topic. |
| Course / unit deleted | The new tables (`lesson_materials`, `material_pages`, `topic_pages`, `topic_versions`, `unit_segmentations`, `pipeline_jobs`, version-scoped `quiz_questions`) cascade via `on delete cascade`; a cleanup step also purges the upload + rendered-PNG objects from Storage — Postgres cascade does not touch Storage. |
| Teacher account deactivated | Their classes / courses are frozen, not deleted: students keep access to already-published topics; flagged for an admin to reassign or archive. |
| Very large unit deck (100+ pages) | The ceiling is combined-payload tokens, not page count; chunk comprehension above a token threshold, then merge the proposed breakdowns. |
| Scanned / handwritten / heavy-equation pages | Multimodal comprehension handles most; genuinely illegible pages are flagged for the teacher. |
| Non-physics / non-secondary subject (Biology, K-2 reading) | Aria's persona is built per course from `subject` + `grade_band` + `teaching_style` — not the hard-coded physics tutor (§6 "Persona"). |

## 14. Compliance & student data

This is a K-12 product heading to real classrooms, so students are
**minors** and the app will hold real personal data about them — name,
email, every question they ask Aria, quiz scores, progress. That triggers
child-data law: **COPPA** (US, under-13s — requires verifiable parental
consent to collect a child's data) and **FERPA** (US student education
records — the school/district holds the rights). In a school context the
school typically acts as the consenting party on parents' behalf.

> This section is a design checklist, **not legal advice**. A qualified
> reviewer must sign off before real students are onboarded.

### v1 baseline — built in Phase 0
- **School-mediated onboarding, never anonymous.** A student never lands
  in a class unseen: a join code creates a `pending` membership and the
  teacher (acting for the school) approves each one. `class_members`
  records `approved_by` / `approved_at` as the audit trail of that
  consent decision.
- **Data minimisation.** Collect only what teaching needs — name, email,
  progress, learning interactions. No date of birth beyond an age band,
  no address, no extra PII.
- **Scoped visibility (RLS).** A teacher sees only their own classes'
  students; a student sees only their own data; no student-to-student
  visibility.
- **Deletion path.** When a student leaves a class or a class is
  archived, there is an explicit route to delete that student's
  personal data and learning records — not just hide them.
- **Privacy policy + terms** surfaced at sign-up and recorded as accepted.

### Pre-launch legal work (NOT in scope to build blind — flagged)
- A **verifiable parental-consent** mechanism for any context the school
  does not cover (direct-to-family use).
- A signed **data-processing agreement (DPA)** with each school /
  district (the FERPA "school official" basis).
- A **data-subject request** process (access / correct / delete).
- Review of where student data flows to **sub-processors** — notably
  that student questions/transcripts are sent to Gemini; confirm the
  model provider's terms permit education / minor use and that data is
  not retained for training.

### Risk to keep visible
Student questions to Aria are free text typed by minors and sent to a
third-party model. Two consequences: (1) it is a data-egress path that
the DPA above must cover; (2) a student may type personal information
into a question — the UI should discourage this and we should not log
raw transcripts beyond what teaching requires.
