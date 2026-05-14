# Architecture

## Overview

K-12 AI Tutor (EduMind) is a multimodal AI tutor for high schoolers. The standout features:

1. **Live chalkboard classroom** — Aria, an AI tutor, narrates a lesson while drawing on a chalkboard SVG. Students watch, ask questions, and sketch their own work.
2. **Socratic Q&A** — never reveals answers; guides with progressive hints.
3. **Vision** — student sketches on the board are captured as images and analyzed by Gemini Vision; Aria responds contextually to what the student drew.
4. **Voice** — bidirectional real-time audio via Gemini Live API. Student talks, Aria talks back.
5. **Adaptive flow** — reactions (🐢 😕 💡 🤯), pace control, peer presence, and quiz-me interrupts.

## Stack

| Layer | Tech | Why |
|---|---|---|
| Frontend | Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS, shadcn/ui, Framer Motion, Zustand, TanStack Query | Modern RSC, fast hydration, mature ecosystem |
| Drawing | `perfect-freehand` + raw SVG | Real chalk feel, lightweight |
| Auth/DB | Supabase (Postgres 15 + pgvector + Auth + Realtime + Storage) | Single vendor, RLS, generous free tier |
| Backend | FastAPI (Python 3.11+), Pydantic v2, `google-genai` SDK | Best Python AI ecosystem, async-first, easy WebSocket |
| AI | Gemini 3.1 Flash (text+vision), 3.1 Flash Live (voice), 3.1 Pro (planner), gemini-embedding-001 (vectors) | Latest GA models, multimodal, low-latency |
| Agent | LangGraph (stateful), custom Socratic state machine | Best fit for multi-step tutoring flow |
| Streaming | Server-Sent Events (Q&A) + WebSocket (voice) | Native browser support; right tool per pattern |
| Deployment | Vercel (web), Fly.io (api), Supabase managed (db) | Each on best-fit platform |

## Data flow

```
┌──────────────────────────────────────────────────────────────┐
│ Browser (Next.js)                                            │
│                                                              │
│   Classroom screen                                           │
│      ├── WhiteboardSVG (lesson chalk drawings)               │
│      ├── SketchLayer (perfect-freehand pen)                  │
│      ├── ReactionsCluster (🐢😕💡🤯)                         │
│      ├── ReplyBar (text + mic)                               │
│      └── CaptionBar (Aria's words)                           │
│                                                              │
│   Q&A → POST /v1/sessions/:id/qa (SSE stream)                │
│   Sketch → POST /v1/sessions/:id/sketch (multipart, SSE)     │
│   Voice → WS /v1/sessions/:id/voice                          │
│                                                              │
└──────────────────┬───────────────────────────────────────────┘
                   │ HTTPS / SSE / WSS
                   │ Auth: Supabase JWT in Authorization header
┌──────────────────▼───────────────────────────────────────────┐
│ FastAPI                                                      │
│                                                              │
│   /v1/sessions/:id/qa  ─→ TutorAgent → SocraticAgent         │
│                            ↓                                  │
│                          GeminiService.stream_text            │
│                            ↓                                  │
│                          gemini-3.1-flash (SSE)               │
│                                                              │
│   /v1/sessions/:id/sketch ─→ VisionAgent                     │
│                                ↓                              │
│                              GeminiService.analyze_image     │
│                                ↓                              │
│                              gemini-3.1-flash (multimodal)   │
│                                                              │
│   /ws/voice  ─→ VoiceAgent (Gemini Live WS bridge)           │
│                  ↕ proxies audio frames bidirectionally       │
│                  gemini-3.1-flash-live-preview                │
│                                                              │
│   All endpoints → Supabase (RLS-gated user data)             │
└─────────────────────────────────────────────────────────────┘
```

## Agent architecture (LangGraph)

See [`agents.md`](agents.md).

Tutor sessions are stateful. Each lesson session has a `agent_state jsonb` blob in Postgres:
- `current_step_idx`
- `student_signals`: `{pace, confusion_level, mastery_estimate, last_reaction}`
- `qa_history`
- `recognized_sketches`
- `hint_level` (0–3 for current step)

LangGraph computes the next action: continue narrating, pause and ask the student, give a hint, generate a quiz, or wait.

## Streaming pattern

**Q&A / sketch (SSE):**

```
event: chunk
data: {"delta": "amplitude is the height"}

event: chunk
data: {"delta": " from rest..."}

event: drawing
data: {"topic": "amplitude"}      // tells frontend to render chalk SVG

event: done
data: {"tokens_used": 142}
```

**Voice (WebSocket):**

```
client → server:  {"type": "audio", "audio": "<base64 PCM>"}
server → client:  {"type": "audio", "audio": "<base64 PCM>"}
server → client:  {"type": "transcript", "text": "amplitude is..."}
server → client:  {"type": "done"}
```

## Security model

- Browser holds Supabase JWT (anon role); attaches as `Authorization: Bearer ...` to every API call.
- FastAPI verifies JWT (HS256 with `SUPABASE_JWT_SECRET`); injects `user_id` into request context.
- Supabase RLS enforces row ownership at the DB level — even with a stolen anon key, users can only read/write their own rows.
- Server-side Supabase service_role calls only from agent traces, never exposed.
- Gemini API key lives only in FastAPI env; never in the browser.

## Local dev

See [README.md](../README.md) and `apps/api/README.md`, `apps/web/README.md`.

## Deployment

See [`deployment.md`](deployment.md).

## Project status

See [`PROGRESS.md`](PROGRESS.md).
