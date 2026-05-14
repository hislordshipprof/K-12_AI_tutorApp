# AI Agent Design

We use **LangGraph** for stateful agent orchestration. Each user lesson session is a graph instance.

## Roles

### TutorAgent (root orchestrator)

- Holds session state: current step, student signals, history.
- Decides next action: narrate, pause, hint, react, quiz, complete.
- Routes events (student question, sketch, reaction, reply, voice utterance) to specialist agents.

### SocraticAgent

- Never reveals the answer in one shot.
- Generates Socratic responses for student questions, replies, and sketch interpretations.
- Hint ladder: each request escalates from gentle prompt → hint → specific guidance. Even the final hint asks the student to compute, not just read.

System prompt (excerpt):

```
You are Aria, a friendly high-school physics tutor (grade 9-12).
Voice: warm, encouraging, curious — never condescending.
You teach the way the best human tutors do: ask before telling.
Rules:
- NEVER give the final numeric or symbolic answer in one message.
- If the student asks "what is X?", first ask what they already know or what they think it is.
- If they say "I don't know", break the problem into a smaller piece they can answer.
- If they got it right, briefly celebrate, then push deeper with a "why" question.
- Use plain language. One concept per message. Short.
```

### VisionAgent

- Receives a PNG (data URL) of the student's sketch on the chalkboard.
- Calls `gemini-3.1-flash` multimodal with prompt: "Look at this student sketch. The current lesson is about [topic]. What did the student likely draw? Respond with JSON: `{shape: 'wave|line|equation|arrow|other', confidence: 0-1, intent: 'string'}`. Be specific."
- Fallback to client-side geometric heuristics (`recognizeStroke` from prototype) if API errors.
- Hands result back to SocraticAgent for response generation.

### VoiceAgent

- Holds a persistent WebSocket session to Gemini Live API (`gemini-3.1-flash-live-preview`).
- Browser opens WS to FastAPI; FastAPI opens WS to Gemini; bidirectional audio frames are proxied.
- Surfaces transcripts to the UI for caption display.
- Reconnect logic with state recovery on drops.

### AssessmentAgent

- Generates a quick MCQ for a topic on demand.
- Scores student answers; updates `topic_progress.score` and `mastery_estimate`.
- On wrong answer, asks SocraticAgent for a Socratic redirect ("walk it back — what moves when a wave passes?").

### PlannerAgent

- Nightly job (or on-demand).
- Reads topic_progress, schedule_blocks, target_score, days_until_exam.
- Generates a 7-day plan: lessons in priority order, quiz days, spaced-repetition flashcard slots.
- Uses `gemini-3.1-pro` for the complex constraint reasoning.

## State machine (lesson session)

```
                ┌─────────┐
                │ Start   │
                └────┬────┘
                     ▼
              ┌──────────────┐
        ┌────▶│ Narrate Step │◀──── auto-advance after N seconds
        │     └──────┬───────┘
        │            │
        │     student input
        │  ┌─────────┼─────────────┬─────────────┬──────────────┐
        │  ▼         ▼             ▼             ▼              ▼
        │ Sketch    Reply       Reaction       Q&A           Voice
        │  │         │             │             │              │
        │  ▼         ▼             ▼             ▼              ▼
        │ Vision   Socratic    Adjust Pace   Socratic       Live API
        │ Agent    Agent       (slower etc)  + draw chalk   bidirectional
        │  │         │             │             │              │
        │  └─────────┴─────────────┴─────────────┴──────────────┘
        │            │
        │            ▼
        │     ┌────────────┐
        │     │ Caption    │
        │     │ updated    │
        │     └────┬───────┘
        │          │
        │  ┌───────┴────────┐
        │  │ More steps?    │
        │  └───┬────────┬───┘
        └─────yes      no
                       │
                       ▼
              ┌──────────────┐
              │ Quiz         │
              └──────┬───────┘
                     ▼
              ┌──────────────┐
              │ Save progress│
              │ Generate     │
              │ auto-notes   │
              └──────┬───────┘
                     ▼
              ┌──────────────┐
              │ Complete     │
              └──────────────┘
```

## Observability

Every agent step writes to `agent_traces`:
- `session_id`, `agent` (which sub-agent), `step` (state-machine state), `input` (jsonb), `output` (jsonb), `latency_ms`.

A simple admin page (`/admin/traces`) shows recent traces for debugging.

## Edge cases

- **Rate limit (429)**: exponential backoff 1s → 2s → 4s, max 3 attempts. On final failure, return a Socratic stub like "Hmm, let me think a sec — try asking again?"
- **Voice WS drop**: auto-reconnect with last 5s of transcript replayed to recover context.
- **Cold start on Fly.io**: keep min instances=1 for `/voice` WS.
- **Sketch too large**: client downsamples to 1024×640 before upload.
- **Non-deterministic LLM**: golden-path snapshots tolerate ±10% length variance; semantic-similarity check for "did the response stay Socratic".
- **Token cost**: per-user daily soft cap (default $0.50); hard cap pauses with a friendly "you've used a lot today — back tomorrow!"
