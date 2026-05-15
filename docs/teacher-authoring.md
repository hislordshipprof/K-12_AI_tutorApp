# Teacher-authored courses — architecture & design

> Status: DESIGN — not yet built. Last updated 2026-05-15.
> Decisions locked: class+join-code linking · slides shown WITH Aria
> annotation · ingest PDF/Word/PowerPoint/plain-text · uploads normalised
> to PDF then read by a multimodal model for comprehension + rendered to
> page images for display · build the design doc first (this file).

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
| Material | A file the teacher uploads for a topic — notes or a slide deck. |
| Lesson | The generated `topics.content` Aria plays — same shape as today. |

## 4. Data model

Reuse the existing hierarchy; add ownership + a teacher layer. New
columns on existing tables:

```
profiles
  + role            text  not null default 'student'   -- 'student' | 'teacher'

courses
  + owner_id        uuid  references profiles(id)        -- null = Recommended
  + origin          text  not null default 'recommended' -- 'recommended' | 'teacher'

topics
  + status          text  not null default 'published'   -- 'draft' | 'published'
  + design_notes    text                                 -- per-lesson teacher guidance
  (existing `content` jsonb still holds the generated lesson;
   `content_provenance` records that it was teacher-generated)
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
  joined_at    timestamptz
  primary key (class_id, student_id)

class_courses                              -- which teacher courses a class sees
  class_id     uuid references classes(id)
  course_id    uuid references courses(id)
  assigned_at  timestamptz
  primary key (class_id, course_id)

lesson_materials                           -- the teacher's raw uploads
  id              uuid pk
  topic_id        uuid references topics(id)
  kind            text        -- 'notes' | 'slides'
  storage_path    text        -- original upload (Supabase Storage key)
  normalized_pdf  text        -- the upload converted to PDF (universal form)
  filename        text
  mime            text
  comprehension   jsonb       -- the model's structured read of the document
  uploaded_by     uuid references profiles(id)
  uploaded_at     timestamptz

topic_slides                               -- rendered slide images for the classroom
  topic_id     uuid references topics(id)
  idx          int             -- slide order
  image_path   text            -- Supabase Storage PNG
  primary key (topic_id, idx)

course_style                               -- teacher's general Socratic style
  course_id     uuid references courses(id) primary key
  teaching_style text           -- "how I teach" — applied to every lesson
```

A teacher course still flows through `units` and `topics` exactly like a
Recommended course, so the classroom needs no change to *load* it.

### RLS (defense-in-depth — schema sketch)
- `classes` / `class_courses` / `lesson_materials`: teacher can read/write
  rows where `teacher_id = auth.uid()` (or the course's `owner_id`).
- `class_members`: a student can insert themselves via a valid join code;
  read their own memberships.
- `topics` of teacher courses: a student may read a topic only if
  `status = 'published'` AND the course is in a `class_courses` row for a
  class the student is a member of.

## 5. Teacher authoring flow

1. Teacher opens the admin board (`/teach`), role-gated.
2. Creates a **class** → gets a join code to share with students.
3. Creates a **course** (subject, title) → adds **units** → **topics**.
   Each topic = one Aria lesson.
4. Sets a course-level **teaching style** once ("how I teach": the
   questions I ask, how I scaffold, my tone).
5. For a topic: **uploads material** (notes + optional slide deck) and
   writes optional per-topic **design notes**.
6. Clicks **Generate lesson** → the pipeline (§6) produces draft
   `topics.content`.
7. **Reviews / edits** the generated steps in the board.
8. **Publishes** (`status = 'published'`) → assigns the course to one or
   more classes (`class_courses`).

## 6. Generation pipeline (teacher source)

A sibling of the existing OpenStax pipeline. Same destination
(`topics.content`), different source.

```
upload → normalize → ┬─ comprehend (model) ─┐
                     └─ render (assets)  ───┴─ generate → validate → review → publish
```

Key principle: **a model comprehends a document; it cannot hand back the
asset files inside it.** So upload splits into two tracks — model
comprehension (for understanding/generation) and mechanical rendering
(for the images we actually display).

- **Normalize → PDF.** Every upload becomes a PDF — the universal
  intermediate that the comprehension model reads AND that we render to
  images. No per-format branching downstream.
  - PDF → used as-is.
  - Word `.docx`, PowerPoint `.pptx` → converted to PDF via a
    server-side LibreOffice headless step (a Docker layer on the API).
  - Plain text / paste → wrapped into a PDF.

- **Comprehend (model track).** The PDF is handed directly to Gemini as
  a multimodal input — the model *reads the whole document*: prose,
  tables, equations, and the figures/diagrams. This far outperforms
  mechanical text scraping (pypdf/python-docx) — it handles scanned
  pages, handwriting, equations and messy layout. Output: structured
  `comprehension` JSON — sections, key points, per-figure descriptions,
  and a page→concept mapping — stored on `lesson_materials`.

- **Render (asset track).** In parallel, each PDF page is rendered to a
  PNG (`pymupdf`) → `topic_slides`. This is the *only* mechanical step
  and it is reliable. The model can *describe* a diagram but cannot
  return the pixels, so to *display* the teacher's real slides/figures
  we render them ourselves.

- **Generate.** The model writes the Aria lesson from the `comprehension`
  JSON + `course_style.teaching_style` + the topic's `design_notes`.
  **Depth scales with the material** — the fixed 8-step rubric is
  dropped; a lesson is as long as the content needs (roughly one step
  per concept / per slide). Each step is mapped to the page it covers.

- **Validate.** Check the lesson actually covers the teacher's key
  points (the existing validator pattern, run against the
  `comprehension` output instead of OpenStax).

- **Review.** Teacher edits in the board before publishing.

Each generated step keeps today's shape and gains an optional slide
reference:

```
{ tts, html, dur, scene, slideIndex? }
```

> **On animations.** PowerPoint builds/transitions are playback
> instructions, not content — they do not transfer and are not a goal.
> We render each slide's *final state*; the "build-up" pacing is
> recreated natively by Aria's word-timed narration and live scene
> annotation, synced to her voice. That replaces slide animation with
> something better.

## 7. Slides + annotation in the classroom

Decision: show the teacher's slides AND let Aria annotate on top.

The scene system already overlays SVG drawings on the chalkboard. For a
teacher lesson step that has a `slideIndex`, the classroom renders:

```
[ slide image (topic_slides[slideIndex]) ]   ← backdrop
[ scene SVG overlay — Aria's annotations  ]   ← existing scene engine
[ word-timed caption                      ]   ← existing
```

So "slides + annotation" reuses the scene engine unchanged — it just
draws over a slide image instead of the dark board. Steps with no
`slideIndex` fall back to the normal chalkboard.

## 8. Student experience

- **Dashboard** — the course list splits into **Recommended** and
  **From your teacher** (the latter resolved via the student's
  `class_members` → `class_courses`).
- **Join a class** — a "Join a class" action takes a join code →
  inserts a `class_members` row.
- **Classroom** — unchanged except it now also renders slide-backed
  steps (§7).

## 9. Admin board (`/teach`, role-gated)

| Page | Purpose |
|---|---|
| `/teach` | Teacher home — classes + courses overview |
| `/teach/classes/[id]` | Roster, join code, assigned courses |
| `/teach/courses/[id]` | Units → topics tree; course teaching-style |
| `/teach/courses/[id]/topics/[id]` | Upload material, design notes, Generate, review/edit steps, Publish |

## 10. API surface (new)

Role-gated under `/v1/teacher/*`:
- `classes` — create / list / roster / regenerate join code
- `courses` / `units` / `topics` — CRUD
- `POST /v1/teacher/topics/{id}/materials` — upload
- `POST /v1/teacher/topics/{id}/generate` — run the pipeline → draft
- `POST /v1/teacher/topics/{id}/publish`

Student-facing:
- `POST /v1/classes/join` — redeem a join code
- the dashboard courses endpoint gains a `group` field
  (`recommended` | `teacher`)

Storage: a Supabase Storage bucket `lesson-materials`; teachers write to
their own prefix; the pipeline reads via the service role.

## 11. Open questions / risks

1. **Becoming a teacher** — invite-only (admin flag) vs self-serve
   signup. Recommend invite-only for v1.
2. **Document conversion** — RESOLVED (§6): all uploads normalise to PDF,
   then a multimodal model comprehends them and `pymupdf` renders page
   images. The one infra dependency is **LibreOffice headless** for
   Word/PowerPoint → PDF — bundled as a Docker layer on the API image
   (~adds build size but is the standard, reliable path). Fallback if we
   want to avoid the layer: accept PDF-only at first and add Office
   conversion in Phase 2.
3. **Re-generation / versioning** — if a teacher re-generates a
   published lesson, keep a version or overwrite. Recommend overwrite +
   a `content_provenance` timestamp for v1.
4. **Upload granularity** — material attaches per *topic* (one topic =
   one lesson). A unit-level upload that auto-splits into topics is a
   later enhancement.

## 12. Phased delivery plan

1. **Foundations** — migration (the §4 schema), `lesson-materials`
   Storage bucket, RLS, a `role` check helper. No UI.
2. **Authoring pipeline** — normalize-to-PDF (LibreOffice headless),
   multimodal comprehension, page-image rendering (`pymupdf`),
   depth-scaled style-aware generation, validator. Proven via a script
   on one real teacher upload.
3. **Admin board** — the `/teach` pages (§9).
4. **Student side** — dashboard split, class join, classroom slide+
   annotation rendering (§7).
5. **Polish** — review workflow, re-generation UX, analytics.

Each phase is independently shippable and verifiable.
