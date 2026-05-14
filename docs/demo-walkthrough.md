# Demo walkthrough — try it in 5 minutes

After running `pnpm dev` (or `cd apps/api && DEV_MODE=true uvicorn app.main:app --reload` + `cd apps/web && pnpm dev`), here's the suggested 5-minute tour.

## Minute 1 — Landing

Visit http://localhost:3000.

You see:
- Hero with "Like having a private tutor, 24 / 7."
- Live chalkboard mock on the right with the wave + amplitude + wavelength markers (chalk-style SVG with feTurbulence filter)
- Floating chips: Raise hand · Smart Q&A · Voice teacher
- Trust avatars + features strip at the bottom

Click **Start free** in the top hero.

## Minute 2 — Onboarding

4-step flow:
1. **Meet Aria** — big pulsing Aria mascot with breathing ring. Click "Let's go."
2. **Grade** — pick "11th grade" (or any).
3. **Courses** — multi-select. Pick AP Physics 1 + AP Calc BC.
4. **Goal** — single-select. Pick "Score a 5 on the AP exam."

Click **Open my classroom** → /dashboard.

## Minute 3 — Dashboard

You see:
- Dark hero band: "Good morning, Alex" + 4 stats (Topics 12, Time 3.5h, Quiz avg 87%, Streak 5)
- Resume Card (indigo, right side): "Wave Properties & Anatomy" with 44% progress bar
- 3 course cards (AP Physics 1 active 28%, Calc BC 12%, Bio 0%)
- Expandable curriculum (Unit 4 "Waves & Sound" is open by default, shows 7 topics)
- Today's schedule with 4 rows + Streak card on the right

Click **Resume lesson** (or "Continue →" on the current topic).

## Minute 4 — Classroom (the core)

Full-bleed dark chalkboard. You see:
- Top: Exit lesson · "Wave Properties & Anatomy" · progress dots · peer presence ("3 here now") · tool cluster (✏️ pen, ⚡ quiz, mute, prev/play/next, outline)
- Center: Aria's chalk drawings auto-advancing through 8 lesson steps
- Bottom-left: 4 reaction emojis (🐢 😕 💡 🤯)
- Bottom: Aria's caption bar ("Prof. Aria · speaking") + Voice button + **Raise hand** button (SPACE key)

**Try these:**

1. **Click "Raise hand"** (or press SPACE).
   - Q&A overlay opens.
   - Click a suggested chip or type: "What is amplitude?"
   - Watch tokens stream in real time from Gemini 2.5 Flash.
   - Aria responds Socratically — asking back, not just defining.

2. **Click the ✏️ pen icon**.
   - Sketch toolbar appears (white/yellow/pink/green chalks).
   - Draw a wavy line on the board.
   - Aria recognizes the shape and asks "Where would you mark the amplitude on it?"
   - Reply bar appears: type "the peaks" and send.

3. **Click ⚡ to quiz yourself**.
   - One-question check pops up.
   - Pick wrong → "Walk it back: think about what actually moves..."
   - Pick right → "Yes! Energy transfer without permanent displacement..."

4. **Try a reaction**.
   - Click 🐢 ("Slow down").
   - Aria's caption changes to "Got it — let me slow down..."

5. **Voice mode** (needs mic permission).
   - Click the Voice button.
   - Hold to speak. Live waveform + transcript.
   - Click "Ask Aria" → the transcript flows into Q&A and Aria responds.

## Minute 5 — Quiz + Complete

- From classroom or directly: visit `/classroom/quiz/wave-properties-anatomy`
- Pick an answer. See Aria's feedback (Socratic on wrong, celebrating on right).
- Click "Next question" → /complete.
- Confetti + trophy + scores + "Next: Wave Speed" button.

## Bonus minute — Other screens

- **Planner** (`/planner`) — 7-day grid with today (Tue 13) highlighted, color-coded blocks, Aria's note card.
- **Notes** (`/notes`) — sticky-note grid + Flashcards tab.
- **History** (`/history`) — 9 lesson rows with chalk thumbnails + scores.

## What to expect after Phase 3 lands

When the AI agent layer is fully wired (TutorAgent + VisionAgent + VoiceAgent):

- Multi-turn Q&A actually remembers context (Aria refers back to your previous question)
- Sketches are analyzed by real Gemini Vision (not just client-side heuristics)
- Voice mode connects to Gemini Live for true bidirectional audio (Aria speaks back with her voice, not Web Speech)
- Reply bar feeds into proper session state
- Reactions are logged + affect pacing

## Known good vs known stubbed

See `docs/HANDOFF.md` → "What's stubbed vs real" table.
