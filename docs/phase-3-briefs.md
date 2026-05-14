# Phase 3 — AI agent layer briefs (dispatch after Phase 2 verifies)

## Agent A1 — TutorAgent + SocraticAgent (FastAPI route + LangGraph state machine)

```
Working dir: /home/claude/K-12_AI_tutorApp/apps/api
Owned: app/agents/ (new dir), app/api/v1/qa.py (replace stub), app/api/v1/reply.py (new), app/api/v1/reaction.py (new), tests/test_agents.py
DO NOT TOUCH: vision, voice, sketch logic (other agents own these).

Build:
1. app/agents/__init__.py
2. app/agents/state.py — TypedDict / Pydantic for SessionState:
     {topic_id, step_idx, mastery, hint_level, last_reaction, qa_history: list[{q,a}], student_signals: dict, recognized_shapes: list}
3. app/agents/prompts.py — System prompts for Aria (Socratic teacher). Include:
   - ARIA_SYSTEM (base persona, age-appropriate, never reveals answer)
   - SOCRATIC_QA_TEMPLATE (for student questions)
   - SOCRATIC_REPLY_TEMPLATE (for student typed replies)
   - REACTION_RESPONSES (dict of slower/confused/got_it/mind_blown → message)
4. app/agents/socratic.py — SocraticAgent class:
   - async respond_to_question(state, q) → stream str
   - async respond_to_reply(state, text) → stream str
   - async respond_to_reaction(state, reaction) → str (single response)
   - All use GeminiService.stream_text with appropriate system prompt
5. app/agents/tutor.py — TutorAgent (orchestrator using LangGraph if simple enough, or just a class with method routing):
   - on_session_start(topic_id) → seed state
   - on_question(state, q) → updates qa_history, routes to SocraticAgent
   - on_reply(state, text)
   - on_reaction(state, reaction)
   - on_complete(state) → returns summary + auto-notes

6. Rewrite app/api/v1/qa.py to use TutorAgent:
   - POST /v1/sessions/{id}/qa  → SSE stream
   - On every chunk, log to agent_traces.

7. Wire app/api/v1/reply.py and reaction.py similarly. Add to router.

8. Tests: mock GeminiService, verify Socratic prompt is correct, verify state updates, verify SSE response.

Verify: pytest -q passes. POST /v1/sessions/test/qa returns SSE events.
```

## Agent A2 — VisionAgent (sketch analysis)

```
Working dir: /home/claude/K-12_AI_tutorApp/apps/api
Owned: app/agents/vision.py, app/api/v1/sketch.py (replace stub), tests/test_vision.py

Build:
1. app/agents/vision.py — VisionAgent class:
   - async analyze_sketch(png_bytes: bytes, current_topic_summary: str, current_step: str) → AsyncGenerator[dict]
     Calls GeminiService.analyze_image with a multimodal prompt:
       """The student drew this on a chalkboard during a lesson about [topic]. Current step: [step].
       Identify what they likely drew (shape, intent). Then respond as Aria the Socratic tutor (never reveal the answer; ask a guiding question).
       Respond as JSON:
       {
         "shape": "wave|line|equation|circle|arrow|writing|other",
         "confidence": 0.0-1.0,
         "intent": "string",
         "aria_response": "Socratic message to the student"
       }
       """
   - Yield events: {type:'recognition', shape, ...}, {type:'chunk', delta:'...'}, {type:'done'}
   - Fallback: if Gemini fails, use the heuristic recognizeStroke logic (port the geometric classifier from prototype tutor-features.jsx).

2. Rewrite app/api/v1/sketch.py:
   - POST /v1/sessions/{id}/sketch
   - Accepts multipart: image (file), question (optional), current_step_idx (int)
   - Returns SSE stream
   - Saves sketch record to DB (sketches table).
   - On every chunk, log to agent_traces.

3. Tests: provide a tiny fixture PNG, mock Gemini, verify the SSE shape.

Verify: pytest test_vision passes. curl multipart POST works.
```

## Agent A3 — VoiceAgent (Gemini Live API bridge)

```
Working dir: /home/claude/K-12_AI_tutorApp/apps/api
Owned: app/agents/voice.py, app/ws/voice.py (replace stub), tests/test_voice.py

CRITICAL: This uses the Gemini Live API. Read the official docs:
https://ai.google.dev/gemini-api/docs/live-api/get-started-websocket
SDK pattern (google-genai >=2.2.0):
  from google import genai
  client = genai.Client(api_key=...)
  async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config={...}) as session:
      # send/recv audio
      await session.send(input={"audio": base64_pcm, "mime_type": "audio/pcm"})
      async for response in session.receive():
          # response.data is audio bytes, response.text is transcript

Build:
1. app/agents/voice.py — VoiceBridge class:
   - async def bridge(client_ws: WebSocket) — accepts the client WebSocket, opens a Gemini Live session,
     forwards client audio chunks to Gemini, forwards Gemini audio + transcript back to client.
   - Protocol envelope:
     client → server: {"type":"audio", "audio":"<base64 PCM 16kHz mono>"} OR {"type":"end_turn"}
     server → client: {"type":"audio", "audio":"<base64 PCM 24kHz>"} OR {"type":"transcript","text":"..."} OR {"type":"error","message":"..."} OR {"type":"done"}
   - Handle reconnects: on Gemini WS drop, attempt reconnect with state preserved (last 5s of transcript).
   - System instruction: same Aria persona (Socratic, never gives answer).

2. Rewrite app/ws/voice.py:
   - WS /v1/sessions/{id}/voice → upgrade, call VoiceBridge.bridge.
   - JWT verification on connection (read from query param ?token= since WS can't easily send Authorization headers — accept both header and query).

3. Tests: mock the Gemini Live client, simulate a client sending audio, verify the bridge forwards correctly.

Verify: pytest test_voice passes. wscat to /ws/voice connects (with mock Gemini key, test endpoint behavior).
```

## Verifier V3

```
- Run `pytest -q` in apps/api → all green
- Start uvicorn, curl all SSE endpoints with sample bodies — verify they stream
- Verify agent_traces table is being populated (count rows after a few requests)
- Run a manual test with the live Gemini key (one Q&A, one sketch analysis) — check that the response is Socratic (not direct answer) and contextually appropriate.
- Capture failures, surface punch list.
```
