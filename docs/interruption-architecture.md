# Interruption architecture

> "The student can interrupt Aria at any time" — across voice, text Q&A, and lesson playback.
> Last updated: 2026-05-14.

## TL;DR

A single state machine governs the classroom. Three "I want to talk" surfaces (mic via Gemini Live VAD, text Q&A overlay, "raise hand" mid-lesson) all converge on the same `flush + bookmark + open-overlay + restore-bookmark` flow. The critical missing pieces today:

1. `apps/web/src/hooks/use-speak.ts` uses `speechSynthesis` — cannot pause at a sample offset. **Replace with an `AudioWorklet` ring-buffer playback hook.**
2. `apps/api/app/agents/voice.py` doesn't surface `server_content.interrupted` to the client. **Add an `{"type":"interrupted"}` frame** so the worklet can flush.
3. `apps/api/app/api/v1/qa.py` keeps consuming Gemini tokens after the SSE client disconnects (no `is_disconnected()` poll + no `aclose()` on the stream). **Wrap generator in `try/finally` + cancellation check.**

Total new + modified code: ~400 LOC, ~3–4 engineer-days.

## Modality 1 — voice barge-in (Gemini Live, WS bidi audio)

### Protocol facts (sourced from official docs)

When server-side VAD detects student speech mid-response, Gemini:
1. Cancels in-flight generation
2. Retains only already-sent tokens in session history
3. Emits `BidiGenerateContentServerContent.interrupted = true`

The client **must** stop playing audio AND **clear the queued PCM playback buffer** the moment it sees this flag — otherwise the model "keeps talking" from the buffer even though generation is dead on the server.

### Decisions

**Automatic VAD by default, manual VAD escape hatch.** K-12 students in noisy bedrooms benefit from auto VAD with conservative settings; a push-to-talk button switches to manual:

```
realtimeInputConfig:
  automaticActivityDetection:
    startOfSpeechSensitivity: START_SENSITIVITY_LOW
    endOfSpeechSensitivity:   END_SENSITIVITY_LOW
    prefixPaddingMs:  200
    silenceDurationMs: 800   # anything < 500ms causes fragmented turns
```

When the student presses push-to-talk: `automaticActivityDetection.disabled = true`, send `activity_start` on press, audio frames while held, `activity_end` on release. **Do NOT use `audio_stream_end` in manual mode** (it's auto-mode only).

**Client-side playback uses `AudioWorkletNode`** — not `<audio>`, not `ScriptProcessorNode`. The native-audio model emits **24 kHz PCM mono**; we enqueue chunks onto a ring buffer in the worklet. On `{type:"interrupted"}` from the server, the main thread posts `{cmd:"flush"}` to the worklet which sets `readIndex = writeIndex` and zero-fills the next render quantum. Browser mic capture is a second worklet, downsampled to 16 kHz before WebSocket send. Full-duplex via a single `AudioContext`; playback flush never blocks capture.

**WebSocket, not WebRTC.** WebRTC's jitter buffer is tuned for packetized network jitter, not for an app dumping bursty AI audio (LiveKit and Pipecat both note you end up writing a "20ms pacer with underrun detection" anyway). For a single-user tutor, WebSocket + AudioWorklet is simpler and the 50-100ms WebRTC win doesn't pay for the complexity. Revisit if we add multi-party classrooms.

## Modality 2 — lesson-playback interruption (Aria narrating scripted steps)

### Today's gap

`useSpeak` wraps `window.speechSynthesis` — fine for the prototype but:
- Can't pause at a sample offset.
- Can't reliably flush mid-utterance across browsers.
- No chunk-level timing for "resume at word 47".

### Plan

Migrate to a **streamed-TTS pipeline** that mirrors the voice-mode playback path. Backend renders Aria's lines as 24 kHz PCM (either via the Gemini Live `AUDIO` modality with a one-shot text turn, or a parallel TTS endpoint). The frontend pipes chunks through the **same AudioWorklet ring buffer** used for voice mode.

Two control commands on the worklet:
- `cmd:"pause"` — stop draining the queue but keep it intact (`paused = true`); resume by setting `paused = false`.
- `cmd:"flush"` — drop the queue entirely (barge-in / answering-coming).

**Step-level resume bookmark.** The classroom shell holds:
```ts
type Bookmark = {
  stepIndex: number;
  audioOffsetMs: number;
  captionCharOffset: number;
};
```
The worklet emits a `progress` event every 100ms with `currentSampleFrame / 24000 * 1000`. The shell snapshots this when entering a Q&A or voice overlay. On "Got it · Resume", we restart the TTS request with `?start_ms=<offset>` (backend trims the leading samples) so Aria picks up mid-sentence instead of re-reading the whole step.

### Raise-hand composition (mid-step interruption)

When the student clicks "Ask" or "Voice" while a step is playing:

1. Shell saves bookmark, sets `playing=false`, posts `{cmd:"flush"}`.
2. If **voice**: open Live WS to `/v1/sessions/{id}/voice`, stream Q&A through it; close on `turn_complete`.
3. If **text**: open SSE to `/v1/sessions/{id}/qa`.
4. On overlay close: restore bookmark and re-request TTS from `start_ms`.

A single Live session is **not kept warm** for the whole lesson — expensive + pollutes the model's context with playback text we don't want. Open Live only for the question window, close immediately. Matches the existing scope of `async with self.gemini.get_live_client(...)` in `voice.py`.

## Modality 3 — text Q&A interruption (SSE Socratic stream)

### Today's gap

`QAOverlay` already wires `AbortController` and aborts on overlay close / "Ask another." But:

1. **FastAPI's `StreamingResponse` doesn't cancel its generator when the client disconnects.** The generator keeps consuming Gemini tokens (we keep paying) until it finishes naturally. Fix in `apps/api/app/api/v1/qa.py`:

   ```python
   async def event_stream():
       stream = gemini.stream_text(...)
       try:
           async for token in stream:
               if await request.is_disconnected():
                   break
               yield _sse({"type":"token","content":token}).encode()
           yield _sse({"type":"done"}).encode()
       except asyncio.CancelledError:
           raise  # let Starlette tear down cleanly
       finally:
           await stream.aclose()  # release the upstream HTTP/2 stream
   ```

   The `google-genai` stream iterator's `aclose()` releases the underlying HTTP/2 stream — without it, the upstream connection lingers.

2. **No visible "Stop generating" button.** Currently a student has to close the overlay to abort. Add a Stop button in `QAOverlay` that calls `abortRef.current?.abort()` and resets `streaming=false` without closing. Also: typing another character in the textarea while `streaming===true` should debounce-auto-abort, so a student can correct themselves mid-answer.

## State machine

State lives in **two places**, deliberately:
- **Frontend** owns `lessonState` (which step, paused/playing, which overlay is open, audio bookmark) — authoritative for UI + what's audible.
- **Backend session row** owns `conversation_state` (last 6 turns, recognized misconceptions, completed steps) — survives reloads.

```
                 ┌──────────────────────────────────────────┐
                 │                                          │
                 ▼                                          │
   ┌─────────IDLE─────────┐                                 │
   │  user opens topic    │                                 │
   └──────────┬───────────┘                                 │
              │ START                                       │
              ▼                                             │
   ┌──── TEACHING_STEP_i ────┐                              │
   │  worklet draining       │── STEP_DONE ─► TEACHING_STEP_{i+1}
   │  caption animating      │                  │
   └──┬────┬─────────┬───┬───┘                  └─► COMPLETE
      │    │         │   │
      │    │         │   └── REACTION ────► REACTING (3.2s) ──► back
      │    │         │
      │    │         └── RAISE_HAND (text) ─► save bookmark ─► QA_STREAMING
      │    │                                                       │
      │    │                                          STOP_GEN ─── │
      │    │                                          QA_DONE      │
      │    │                                          ABORT────────┘
      │    │                                                       ▼
      │    │                                              restore bookmark
      │    │                                                       │
      │    │                                                       ▼
      │    │                                                TEACHING_STEP_i
      │    │
      │    └── RAISE_HAND (voice) ─► save bookmark ─► LIVE_LISTENING
      │                                                  │
      │                          STUDENT_SPEAKS ─────────┤
      │                                                  ▼
      │                                            LIVE_ANSWERING
      │                                                  │  interrupted=true ─┐
      │                                                  │                    │
      │                                                  │ ◄──────────────────┘
      │                                                  │  flush worklet
      │                                                  │  turn_complete
      │                                                  ▼
      │                                            restore bookmark ─► TEACHING_STEP_i
      │
      └── PAUSE ─► PAUSED (bookmark held) ─► PLAY ─► TEACHING_STEP_i
```

**Events**: `START`, `STEP_DONE`, `PAUSE`, `PLAY`, `RAISE_HAND_TEXT`, `RAISE_HAND_VOICE`, `STUDENT_SPEAKS`, `GEMINI_INTERRUPTED`, `TURN_COMPLETE`, `QA_TOKEN`, `QA_DONE`, `STOP_GEN`, `REACTION`, `RESUME`.

## API surface changes

### WebSocket envelope (`apps/api/app/agents/voice.py`)

**New client → server frames:**
- `{"type":"interrupt"}` — client-initiated barge-in (e.g. user clicks "stop talking"). Server forces the model to yield even without VAD-detected audio.
- `{"type":"activity_start"}` / `{"type":"activity_end"}` — only used in manual-VAD mode.

**New server → client frames:**
- `{"type":"interrupted"}` — emitted when `response.server_content.interrupted is True`. **This is the critical missing piece** — the worklet flushes on this frame.
- `{"type":"generation_complete"}` — distinct from `turn_complete`; lets the UI dim the "Aria speaking" indicator before the student replies.

### SSE additions (`apps/api/app/api/v1/qa.py`)

Wrap the generator in `try/finally: await gemini_stream.aclose()`. Poll `request.is_disconnected()` between tokens. Map `asyncio.CancelledError` to a clean stream end (no `error` event).

## Minimum changes to existing files

### `apps/api/app/agents/voice.py` (~40 LOC added)
- Pass `realtime_input_config` (auto VAD tuning) through `gemini.get_live_client(...)`.
- In `gemini_to_client`: read `server_content.interrupted` and `server_content.generation_complete` → emit dedicated frames before/alongside `turn_complete`.
- In `client_to_gemini`: handle the three new client frame types; route `activity_start/end` to `session.send_realtime_input(activity_start=ActivityStart())` etc.
- Make `_signal_end_of_turn` aware of auto vs manual mode (it currently sends `audio_stream_end=True` which is wrong under manual VAD).

### `apps/web/src/components/classroom/classroom-shell.tsx`
- Replace `useSpeak` (speechSynthesis) with new `useTtsPlayback` hook backed by an AudioWorklet ring buffer. Expose `pause / flush / resume / seekToMs / onProgress`.
- On overlay open (`qaOpen`, `voiceOpen`, `quizMeOpen`, `sketchOn`): call `tts.flush()` (not just `stopSpeak()`); snapshot bookmark.
- On overlay close: re-request the active step's TTS from the saved offset.

### `apps/web/src/components/classroom/voice-mode.tsx` + new `useGeminiLive` hook
- Replace browser SpeechRecognition (`useListen`) with a real WS to `/v1/sessions/{id}/voice` using the existing bridge.
- On `{type:"interrupted"}` → `worklet.port.postMessage({cmd:"flush"})`.
- "Cancel" button sends `{type:"interrupt"}` then closes the socket.

### `apps/web/src/components/classroom/qa-overlay.tsx` (small)
- Add a "Stop generating" button bound to `abortRef.current.abort()`.
- Auto-abort on next keystroke when `streaming === true` (so typing a follow-up cancels).

### New files
- `apps/web/src/audio/playback-worklet.ts` — ring-buffer worklet
- `apps/web/src/audio/capture-worklet.ts` — mic → 16k PCM
- `apps/web/src/hooks/use-tts-playback.ts`
- `apps/web/src/hooks/use-gemini-live.ts`

Total: ~400 LOC.

## Effort estimate

| Stage | Days |
|---|---|
| AudioWorklet playback + capture worklets | 1.0 |
| `useTtsPlayback` + bookmark plumbing | 0.5 |
| `useGeminiLive` (browser WS client) | 0.5 |
| `voice.py` envelope additions + VAD config plumbing | 0.5 |
| `qa.py` cancellation + Stop button + auto-abort UX | 0.5 |
| State-machine wiring in `classroom-shell.tsx` | 0.5 |
| Manual + Playwright verification across all 3 modalities | 0.5 |
| **Total** | **~3.5–4 eng-days** |

## Open questions

1. **Do we render Aria's lesson TTS via Gemini Live AUDIO modality (one-shot text turn) or a separate TTS service?** Live is cheaper to integrate (same path as voice mode) but adds a new model dep per step. Pick after we ingest the first batch of content and have real lesson text to test.
2. **Caption sync** — the HTML caption today animates independently of TTS. Once playback emits `progress` events, we can drive the caption from the worklet directly (`captionCharOffset = round(progress * captionLen / dur)`).
3. **WebRTC, later** — if we add multi-party (study buddy mode) or screen share, switch to WebRTC for proper jitter handling. Until then, WebSocket.
4. **Mobile Safari constraints** — `AudioWorklet` ships on Safari 14.5+, but iOS requires user-gesture to start the `AudioContext`. The first "play lesson" tap counts as a gesture; subsequent resumes from background may need a re-tap.

## Primary sources

- **Gemini Live API capabilities** (interrupted, VAD config, activityStart/End): https://ai.google.dev/gemini-api/docs/live-api/capabilities
- **Gemini Live overview** (barge-in, native VAD): https://ai.google.dev/gemini-api/docs/live
- **Gemini 3.1 Flash Live preview** (breaking config changes): https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-live-preview
- **Vertex Live reference** (`BidiGenerateContentServerContent` schema): https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/multimodal-live
- **Google reference impl** (live-api-web-console — canonical "flush on interrupted"): https://github.com/google-gemini/live-api-web-console
- **OpenAI Realtime VAD** (comparison + `speech_started`, `interrupt_response`): https://platform.openai.com/docs/guides/realtime-vad
- **FastAPI SSE cancellation** (`request.is_disconnected()` + `asyncio.CancelledError`): https://github.com/fastapi/fastapi/discussions/7572
- **LiveKit "WebRTC vs WebSockets" tradeoffs**: https://livekit.com/blog/why-webrtc-beats-websockets-for-voice-ai-agents
- **Pipecat Gemini Live integration**: https://docs.pipecat.ai/guides/features/gemini-live
- **AudioWorklet (MDN)**: https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Using_AudioWorklet
