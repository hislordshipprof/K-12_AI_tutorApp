# Teacher-authored courses — architecture & design

> Status: DESIGN — not yet built. Last updated 2026-05-15.
> Decisions locked: class+join-code linking · slides shown WITH Aria
> annotation · ingest PDF/Word/PowerPoint/plain-text · uploads normalised
> to PDF then read by a multimodal model for comprehension + rendered to
> page images for display · material is uploaded per UNIT and the model
> segments it into topics the teacher confirms · build the design doc
> first (this file).

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
  + role            text  not null default 'student'   -- 'student' | 'teacher'

courses
  + owner_id        uuid  references profiles(id)        -- null = Recommended
  + origin          text  not null default 'recommended' -- 'recommended' | 'teacher'

topics
  + status          text  not null default 'published'   -- 'draft' | 'published'
  + design_notes    text                                 -- per-lesson teacher guidance
  + source_material uuid  references lesson_materials(id) -- which upload it came from
  + source_pages    int[]                                -- page range within that material
  (existing `content` jsonb still holds the generated lesson;
   `content_provenance` records that it was teacher-generated.
   For teacher courses, topic rows are CREATED by segmentation — see §6 —
   not pre-authored by the teacher.)
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
  unit_id         uuid references units(id)  -- uploaded at the UNIT level —
                                             -- one material may cover many topics
  kind            text        -- 'notes' | 'slides' | 'practice'
  storage_path    text        -- original upload (Supabase Storage key)
  normalized_pdf  text        -- the upload converted to PDF (universal form)
  filename        text
  mime            text
  comprehension   jsonb       -- the model's structured read + proposed
                              -- topic segmentation (see §6)
  uploaded_by     uuid references profiles(id)
  uploaded_at     timestamptz

material_pages                             -- one rendered page image per source page
  material_id  uuid references lesson_materials(id)
  idx          int             -- page order within the material
  image_path   text            -- Supabase Storage PNG
  primary key (material_id, idx)
  -- a topic claims a subset of these via topics.source_pages

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

A single upload often covers a whole unit — many topics. Teachers
organise by unit, not by our DB's topic rows, so they upload at the
unit level and the system discovers the topics inside.

1. Teacher opens the admin board (`/teach`), role-gated.
2. Creates a **class** → gets a join code to share with students.
3. Creates a **course** (subject, title) and a **unit**.
4. Sets a course-level **teaching style** once ("how I teach": the
   questions I ask, how I scaffold, my tone).
5. **Uploads the unit's material** — one or more files (notes, slide
   decks, worksheets). No need to pre-chop it per topic.
6. The pipeline (§6) comprehends the material and **proposes a topic
   breakdown** — "this material = topics A, B, C with these page
   ranges."
7. **Teacher confirms the breakdown** — rename / merge / split / reorder
   / drop proposed topics. This is the key human checkpoint: the model
   proposes the structure, the teacher disposes.
8. On confirm, a `topics` row is created per topic and a lesson is
   **generated** for each (§6) → draft `topics.content`.
9. **Reviews / edits** the generated steps per topic in the board.
10. **Publishes** (`status = 'published'`) → assigns the course to one
    or more classes (`class_courses`).

## 6. Generation pipeline (teacher source)

A sibling of the existing OpenStax pipeline. Same destination
(`topics.content`), different source.

```
upload(unit) → normalize → ┬─ comprehend + SEGMENT (model) ─┐
                           └─ render pages (assets) ────────┴─→ teacher confirms
   topic breakdown → [per topic] generate → validate → review → publish
```

Two principles drive this:
1. **A model comprehends a document; it cannot hand back the asset files
   inside it.** Upload splits into a comprehension track (understanding)
   and a mechanical render track (the images we display).
2. **One upload usually spans several topics.** The comprehension step
   also *segments* — turning an unstructured document into a proposed
   topic structure the teacher then confirms.

- **Normalize → PDF.** Every upload becomes a PDF — the universal
  intermediate that the comprehension model reads AND that we render to
  images. No per-format branching downstream.
  - PDF → used as-is.
  - Word `.docx`, PowerPoint `.pptx` → converted to PDF via a
    server-side LibreOffice headless step (a Docker layer on the API).
  - Plain text / paste → wrapped into a PDF.

- **Comprehend + segment (model track).** All of the unit's uploads are
  combined and handed to Gemini as multimodal input. The model *reads
  the whole document* — prose, tables, equations, figures — far better
  than mechanical scraping (handles scanned pages, handwriting, messy
  layout). It outputs structured `comprehension` JSON:
  - per-section key points + per-figure descriptions;
  - a **proposed topic breakdown** — a list of distinct topics, each
    with a title, summary, and the page ranges that cover it;
  - a classification of each material as `notes` / `slides` / `practice`
    and a flag on any section too thin to teach.
  The teacher confirms/edits this breakdown (§5.7) before generation.

- **Render (asset track).** In parallel, each PDF page is rendered to a
  PNG (`pymupdf`) → `material_pages`. This is the *only* mechanical step
  and it is reliable. The model can *describe* a diagram but cannot
  return the pixels, so to *display* the teacher's real slides/figures
  we render them ourselves. Each confirmed topic later claims a page
  subset via `topics.source_pages`.

- **Generate (per confirmed topic).** For each topic the teacher
  confirmed, the model writes the Aria lesson from that topic's slice of
  the `comprehension` JSON + `course_style.teaching_style` + the topic's
  `design_notes`. **Depth scales with the material** — the fixed 8-step
  rubric is dropped; a lesson is as long as the content needs. Each step
  maps to the page it covers.

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
[ slide image (material_pages for the topic's source_pages) ]  ← backdrop
[ scene SVG overlay — Aria's annotations  ]                    ← existing scene engine
[ word-timed caption                      ]                    ← existing
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
| `/teach/courses/[id]` | Units tree; course teaching-style |
| `/teach/courses/[id]/units/[id]` | Upload unit material → review the proposed topic breakdown → confirm |
| `/teach/courses/[id]/topics/[id]` | Per-topic design notes, review/edit generated steps, Publish |

## 10. API surface (new)

Role-gated under `/v1/teacher/*`:
- `classes` — create / list / roster / regenerate join code
- `courses` / `units` — CRUD
- `POST /v1/teacher/units/{id}/materials` — upload one or more files
- `POST /v1/teacher/units/{id}/segment` — comprehend + return a proposed
  topic breakdown for the teacher to confirm
- `POST /v1/teacher/units/{id}/topics` — confirm the breakdown → create
  the `topics` rows (with `source_material` + `source_pages`)
- `POST /v1/teacher/topics/{id}/generate` — generate that topic's lesson
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
4. **Upload granularity** — RESOLVED (§5, §6): material is uploaded at
   the *unit* level; one upload may cover several topics. The
   comprehension step segments it into a proposed topic breakdown the
   teacher confirms. Course-level upload (one doc → a whole course) is a
   later enhancement.
5. **Very large uploads** — a whole unit may be a 100+ page deck. Gemini's
   long context handles most, but cost/latency rise. May need chunked
   comprehension above a page threshold (see §13).

## 12. Phased delivery plan

1. **Foundations** — migration (the §4 schema), `lesson-materials`
   Storage bucket, RLS, a `role` check helper. No UI.
2. **Authoring pipeline** — normalize-to-PDF (LibreOffice headless),
   multimodal comprehension + **topic segmentation**, page-image
   rendering (`pymupdf`), depth-scaled style-aware generation,
   validator. Proven via a script on one real unit upload.
3. **Admin board** — the `/teach` pages (§9), including the
   confirm-the-breakdown screen.
4. **Student side** — dashboard split, class join, classroom slide+
   annotation rendering (§7).
5. **Polish** — review workflow, re-generation UX, analytics.

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
| Over- / under-splitting (blurred boundaries) | Teacher confirm step can merge / split / add / drop proposed topics. |
| Thin / sparse material (a few bullet words) | Quality gate: the model flags a section as "too thin to teach"; the board asks the teacher to add notes rather than generate a hollow, hallucination-prone lesson. |
| Slides + a separate notes doc for the same unit | Combined comprehension fuses them — notes add depth, slides add visuals; they need not align 1:1. |
| Worksheets / practice mixed in with teaching material | Classified as `practice`, not turned into a lesson — a later enhancement can feed them into quizzes. |
| Non-contiguous coverage (covers A, then B, then back to A) | Comprehension maps concept→pages; `topics.source_pages` is a page **set**, not a single range. |
| Teacher's unit names don't match AP CED | Fine — teacher courses have their own unit tree (`owner_id`); no forced alignment. |
| Re-upload of revised material | Re-segment proposes a fresh breakdown; teacher re-confirms. v1 overwrites (no auto-merge of prior edits). |
| Very large unit deck (100+ pages) | Chunk the comprehension above a page threshold, then merge the proposed breakdowns. |
| Scanned / handwritten / heavy-equation pages | Multimodal comprehension handles most; genuinely illegible pages are flagged for the teacher. |
