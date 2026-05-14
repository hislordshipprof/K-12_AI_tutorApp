# API Reference

Base URL (dev): `http://localhost:8000`
Base URL (prod): `https://api.k12tutor.app` (when deployed)
All endpoints under `/v1` require `Authorization: Bearer <supabase_jwt>`. `/health` and `GET /v1/courses` are public.

## Streaming (SSE) envelope

```
event: chunk
data: {"delta": "...partial text..."}

event: drawing
data: {"topic": "amplitude", "svg": "<svg>...</svg>" }    // optional, when API wants UI to render chalk

event: done
data: {"tokens": 142, "duration_ms": 1820}

event: error
data: {"message": "rate_limit", "retryable": true}
```

## Endpoints

### Auth (Supabase handles directly)
Browser uses Supabase Auth SDK; the backend doesn't expose login endpoints. JWT is passed back via `Authorization: Bearer ...`.

### `GET /health` → 200
```json
{"ok": true, "models": {"text": "gemini-3.1-flash", "live": "gemini-3.1-flash-live-preview", ...}}
```

### `GET /v1/courses` → 200
List public courses + the user's enrollment + progress (if authed).
```json
[{"id": "...", "slug": "ap-physics-1", "title": "AP Physics 1", "icon_emoji": "⚛️", "progress_pct": 28, ...}]
```

### `GET /v1/topics/{id}` → 200
Full topic with lesson steps.
```json
{
  "id": "...", "name": "Wave Properties & Anatomy", "duration_min": 18,
  "content": {"steps": [{"tts": "...", "html": "...", "dur": "01:20"}, ...]}
}
```

### `POST /v1/sessions` → 201
Start a lesson session.
```json
// Request
{"topic_id": "..."}
// Response
{"id": "uuid", "topic_id": "...", "started_at": "...", "agent_state": {"step_idx": 0, ...}}
```

### `GET /v1/sessions/{id}` → 200
Current state.

### `PATCH /v1/sessions/{id}` → 200
Update local step / agent_state from client (e.g., when student manually navigates).
```json
{"agent_state": {"step_idx": 3}}
```

### `POST /v1/sessions/{id}/qa` → SSE stream
Ask a question. Streams Aria's response.
```json
{"q_text": "What is amplitude?", "source": "text"}
```

### `POST /v1/sessions/{id}/sketch` → SSE stream
Upload student sketch image (multipart), get Socratic analysis.
- form fields: `image` (file), `question` (optional string), `current_step_idx` (int)

### `POST /v1/sessions/{id}/reply` → SSE stream
Student typed reply to an Aria question.
```json
{"text": "I think it's the height"}
```

### `POST /v1/sessions/{id}/reaction` → 200
Student tapped a reaction emoji. Updates agent state pacing.
```json
{"reaction": "confused"}  // or "slower" | "got_it" | "mind_blown"
```

### `WS /v1/sessions/{id}/voice` → upgrade
Bidirectional audio bridge to Gemini Live.
Client sends `{"type": "audio", "audio": "<base64 PCM 16kHz>"}`.
Server forwards `{"type": "audio" | "transcript" | "done"}`.

### `POST /v1/sessions/{id}/complete` → 200
Save progress, generate auto-notes, increment streak.

### `GET /v1/quiz/{topic_id}` → 200
Get an MCQ for the topic.
```json
{"question": "...", "options": ["A...", "B...", "C...", "D..."], "correct": 2}
```

### `POST /v1/quiz/{topic_id}/attempt` → 200
Score answer, return Socratic feedback.
```json
// Request
{"question_idx": 0, "picked_idx": 2}
// Response
{"correct": false, "feedback": "Walk it back: think about what actually moves...", "mastery_delta": -0.05}
```

### `GET /v1/notes` → 200
List user's notes. Query params: `?topic_id=...&kind=auto|user|qa`.

### `POST /v1/notes` → 201
Create a note.

### `PATCH /v1/notes/{id}` → 200
Update.

### `DELETE /v1/notes/{id}` → 204

### `GET /v1/flashcards/due` → 200
SM-2 due flashcards.

### `POST /v1/flashcards/{id}/review` → 200
```json
{"quality": 4}  // SM-2: 0=blackout, 5=perfect
```

### `GET /v1/planner/week` → 200
This week's schedule blocks.

### `POST /v1/planner/regenerate` → 200
Run PlannerAgent. Replaces upcoming blocks.

## Error envelope

```json
{
  "error": {
    "code": "rate_limit" | "unauthorized" | "validation" | "not_found" | "internal",
    "message": "human readable",
    "details": {...optional...}
  }
}
```

HTTP status mirrors the code (429, 401, 422, 404, 500).
