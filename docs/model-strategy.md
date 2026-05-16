# Model strategy — which Gemini (and Claude) model runs where

> Status: DESIGN / LIVING DOC — last updated 2026-05-15.
> Companion to `docs/teacher-authoring.md`. This file is the single
> source of truth for *which model powers which surface* and why.
> Two items here are time-critical (the 2.5 deprecation and the
> `fly.toml` drift) — see §6.

## 1. Goal

The app spans voice, vision, text, content generation, and (soon)
teacher-material comprehension. Each surface has a different
quality / latency / cost profile. This doc maps every surface to the
right model so we (a) survive the 2.5 deprecation, (b) stop paying for
a model heavier than the job needs, and (c) reserve frontier models for
the few calls that actually move the needle.

## 2. Current state (2026-05-15)

Configured in `apps/api/app/core/config.py`:

| Slot | Model now | Powers |
|---|---|---|
| `text` | `gemini-3.1-flash-lite` | Aria's Socratic replies, free-form Q&A |
| `vision` | `gemini-3.1-flash-lite` | reading student sketches / uploaded images |
| `live` | `gemini-2.5-flash-native-audio-latest` | voice mode **and** the `/v1/tts` endpoint |
| `pro` | `gemini-pro-latest` | OpenStax → lesson content generation |
| `embed` | `gemini-embedding-2` | RAG retrieval over course content |

Plus **Claude Sonnet 4.6** (`claude-sonnet-4-6`) for offline
scene-drawing generation (Phase C of the live-drawing system).

Two defects independent of any model choice:
- The `live` slot is the **only** thing still on the Gemini 2.5 family,
  which deprecates **2026-06-17**.
- `apps/api/fly.toml` is pinned *behind* the code defaults
  (`gemini-2.5-flash` / `gemini-2.5-pro` / `gemini-embedding-001`) — a
  production deploy today would run deprecated models.

## 3. Voice — split one job into two

Today `/v1/tts` (`apps/api/app/api/v1/tts.py`) makes the **Live
audio-to-audio model do read-aloud TTS**. It works but it is a hack: a
conversational model spun up per lesson step, with a deliberately
stunted system prompt because long persona prose makes the model
*explain* the text instead of *reading* it. Narration and conversation
are different jobs; Gemini now has a dedicated model for each.

### 3a. Live voice mode → `gemini-3.1-flash-live-preview`
The real-time, bidirectional, barge-in voice conversation
(`apps/web/src/hooks/use-gemini-live.ts`, `apps/api/app/ws/voice.py`).
Migrate off `gemini-2.5-flash-native-audio-latest`. This is the
**deprecation fix**, not an optimization. Preview status is acceptable —
the current value is itself a moving `latest` alias.
- **Risk to test:** barge-in / interruption timing is load-bearing.
  Verify the interrupt path end-to-end after the swap.

### 3b. Lesson-step TTS → `gemini-3.1-flash-tts-preview`
A new dedicated slot (`tts`). Why it wins:
- TTS models read **verbatim** by design — the "model editorializes"
  hack in `tts.py` disappears.
- One-shot generate call replaces the per-step Live-session
  `_collect_pcm` drain → lower latency, lower cost (no Live session
  overhead per step).
- **Expressive audio tags** (pause / slow / emphasis) pair naturally
  with the word-timed captions and the narration-driven step advance.

This decouples narration from conversation. Live is then used **only**
for the conversational voice mode.

## 4. Image — narrow fit; do NOT touch the core loop

The teaching loop is **live SVG annotation revealed word-by-word**. A
generated raster cannot do timed reveal, is heavier, and is less
accessible. The scene engine stays as-is. Image generation has only two
cosmetic niches, both low priority:

- **Course / topic cover art** — teacher courses need visual identity.
  Use **Nano Banana 2** (`gemini-3.1-flash-image-preview`, the
  high-volume / efficient one — not the 4K Pro). Generate once at
  publish time, cache. Phase 5 polish.
- **Teacher figures** — *rejected.* A generated physics diagram can be
  subtly wrong. We render the teacher's real slide via `pymupdf`
  instead. Image-gen is never used for instructional diagrams.

## 5. Video — defer Veo entirely

Veo 3.1 is **not real-time** (seconds-to-minutes per clip), so it cannot
participate in the live lesson loop — the SVG scene system already won
that trade-off. The only conceivable fit is a pre-rendered ~6s
topic-intro "hook" generated once at authoring time, which is pure
polish and carries real per-clip cost across hundreds of topics.
**Decision: parked.** Revisit only if there is a marketing / engagement
driver.

## 6. Comprehension & generation tiering (teacher pipeline)

The teacher-authoring pipeline (`docs/teacher-authoring.md` §6) has one
very high-stakes call — **comprehend + segment** a whole unit upload
(e.g. the Fluids deck: 76 slides, 306 images). That single call sets the
topic structure the teacher then confirms. `flash-lite` is too light
for it.

| Pipeline step | Model | Rationale |
|---|---|---|
| Comprehend + segment a unit upload | `gemini-3-flash-preview`, escalating to `gemini-3.1-pro-preview` for large / messy decks | Runs once per upload, not latency-sensitive; quality sets the whole topic tree |
| Per-topic lesson generation | `pro` slot (`gemini-3.1-pro-preview`) | Reasoning-heavy, runs per topic |
| Quiz generation | same as generation | — |
| Per-step cheap touch-ups, sketch checks | `flash-lite` | High-volume, low-stakes |

## 7. Embeddings

`gemini-embedding-2` is **multimodal** — text, images, video, audio,
PDFs in one space. For the teacher pipeline this means rendered slide
**images** and notes **text** can be embedded together, which directly
serves the §13 "non-contiguous coverage" case (mapping a concept to the
set of pages that cover it). Keep `gemini-embedding-2`; use its
multimodal capability in the teacher pipeline, not just text RAG.

## 8. Version-pinning hygiene

`latest` aliases hot-swap with only ~2 weeks' notice. The content
pipeline bakes the model name into a **provenance hash**
(`apps/api/app/content/cli.py`) — a silent hot-swap corrupts provenance.
Rule:
- Generation / content paths → **pin an explicit model string**
  (stable or dated preview), never `*-latest`.
- Non-provenance paths (voice, vision) → `latest` / preview is fine.

## 9. Migration plan (prioritized)

| # | Change | Priority | Notes |
|---|---|---|---|
| 1 | `live` → `gemini-3.1-flash-live-preview` | **Urgent** | 2.5 deprecates 2026-06-17; test barge-in |
| 2 | Fix `fly.toml` to match code defaults | **Urgent** | prod currently runs deprecated models |
| 3 | New `tts` slot → `gemini-3.1-flash-tts-preview`; rewrite `/v1/tts` as one-shot | High | kills the Live-as-TTS hack, cuts cost |
| 4 | Pin `pro` → explicit `gemini-3.1-pro-preview` | Medium | provenance integrity |
| 5 | Add `segment` slot → `gemini-3-flash-preview` | With teacher Phase 2 | comprehension/segmentation |
| 6 | Course cover art via Nano Banana 2 | Phase 5 | cosmetic |
| 7 | Veo intro hooks | Parked | revisit only with a clear driver |

## 10. Open questions

1. **TTS expressive tags** — do we author pacing tags into
   `topics.content` steps, or let the TTS model infer pacing? Decide
   when slot 3 lands.
2. **Live Preview stability** — `gemini-3.1-flash-live-preview` is
   Preview; watch for a stable release before the 2.5 shutdown and
   re-pin if one appears.
3. **Segmentation escalation trigger** — what page count / "messiness"
   signal flips a unit from `gemini-3-flash-preview` to
   `gemini-3.1-pro-preview`? Tune empirically in Phase 2.
