# K-12 AI Tutor — FastAPI Backend

Gemini-powered backend for the K-12 AI Tutor classroom.

- **REST + SSE** — `/v1/*` endpoints for lessons, sessions, quizzes, notes, planner, flashcards.
- **WebSocket** — `/ws/voice` bridges the browser to the **Gemini Live API** for real-time voice.
- **Auth** — Supabase JWT verification (HS256). A dev-only `X-Dev-User-Id` header is honoured when `DEV_MODE=true` or `LOG_LEVEL=DEBUG`.
- **Models** — Uses the new `google-genai` SDK (NOT the deprecated `google-generativeai`).

## Run locally

```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs (Swagger)
# → http://localhost:8000/health
```

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## Environment

Copy `../../.env.example` to `apps/api/.env`, then fill in:

```
GEMINI_API_KEY=...
SUPABASE_URL=https://YOUR.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_JWT_SECRET=...
```

Default models (April 2026):

| Slot          | Model                          |
| ------------- | ------------------------------ |
| `text`        | `gemini-3.1-flash`             |
| `vision`      | `gemini-3.1-flash`             |
| `live` (ws)   | `gemini-3.1-flash-live-preview`|
| `pro`         | `gemini-3.1-pro`               |
| `embeddings`  | `gemini-embedding-001`         |

## Layout

```
apps/api/
├── app/
│   ├── main.py                # FastAPI app + lifespan + middleware
│   ├── core/
│   │   ├── config.py          # pydantic-settings (env-driven)
│   │   ├── logging.py         # structlog config (JSON or pretty)
│   │   └── security.py        # Supabase JWT verification + auth dep
│   ├── services/
│   │   ├── gemini.py          # GeminiService: stream_text / analyze_image / embed / Live
│   │   └── supabase.py        # anon + service-role client factories
│   ├── models/schemas.py      # Pydantic v2 schemas mirroring the DB
│   ├── api/v1/                # versioned routers (health, courses, sessions,
│   │                          # qa, sketch, quiz, notes, planner, flashcards)
│   └── ws/voice.py            # WebSocket → Gemini Live (stub)
├── tests/                     # pytest + pytest-asyncio
├── pyproject.toml             # Poetry-compatible project metadata
├── requirements.txt           # Pinned for Fly.io / Render deploys
└── Dockerfile                 # Multi-stage (python:3.12-slim)
```

## Deploy (Docker)

```bash
docker build -t k12-tutor-api .
docker run --rm -p 8000:8000 --env-file .env k12-tutor-api
```
