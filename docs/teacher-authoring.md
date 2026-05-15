# Teacher-authored courses — architecture & design

> Status: DESIGN — not yet built. Last updated 2026-05-15.
> Decisions locked: class+join-code linking · slides shown WITH Aria
> annotation · ingest PDF/Word/PowerPoint/plain-text · build the design
> doc first (this file).

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
  id            uuid pk
  topic_id      uuid references topics(id)
  kind          text          -- 'notes' | 'slides'
  storage_path  text          -- Supabase Storage object key
  filename      text
  mime          text
  extracted_text text          -- text pulled out at upload time
  uploaded_by   uuid references profiles(id)
  uploaded_at   timestamptz

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
upload → extract → generate → validate → review → publish
```

- **Extract** — pull text from each upload:
  - PDF → `pymupdf` (text; also renders page images for slides).
  - Word `.docx` → `python-docx`.
  - PowerPoint `.pptx` → `python-pptx` (text). For slide *images*, the
    reliable path is render-from-PDF: convert the deck to PDF, then
    `pymupdf` renders each page → PNG → `topic_slides`. (Decision: ask
    teachers to also export the deck as PDF, or run a server-side
    LibreOffice conversion — see §11.)
  - Plain text / paste → stored as-is.
- **Generate** — Gemini/Claude receives: the extracted material +
  `course_style.teaching_style` + the topic's `design_notes`. It writes
  the Aria lesson steps. **Depth scales with the material** — the fixed
  8-step rubric is dropped; a lesson is as long as the content needs
  (roughly one step per concept / per slide).
- **Validate** — check the lesson actually covers the teacher's key
  points (the existing validator pattern, run against the teacher's
  material instead of OpenStax).
- **Review** — teacher edits in the board before publishing.

Each generated step keeps today's shape and gains an optional slide
reference:

```
{ tts, html, dur, scene, slideIndex? }
```

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
2. **pptx → slide images** — `python-pptx` gives text but not rendered
   images. Options: (a) teacher also uploads the deck as PDF; (b)
   server-side LibreOffice headless conversion. Recommend (a) for v1.
3. **Re-generation / versioning** — if a teacher re-generates a
   published lesson, keep a version or overwrite. Recommend overwrite +
   a `content_provenance` timestamp for v1.
4. **Upload granularity** — material attaches per *topic* (one topic =
   one lesson). A unit-level upload that auto-splits into topics is a
   later enhancement.

## 12. Phased delivery plan

1. **Foundations** — migration (the §4 schema), `lesson-materials`
   Storage bucket, RLS, a `role` check helper. No UI.
2. **Authoring pipeline** — extractors (pdf/docx/pptx/text), slide
   rendering, depth-scaled style-aware generation, validator. Proven
   via a script on one real teacher upload.
3. **Admin board** — the `/teach` pages (§9).
4. **Student side** — dashboard split, class join, classroom slide+
   annotation rendering (§7).
5. **Polish** — review workflow, re-generation UX, analytics.

Each phase is independently shippable and verifiable.
