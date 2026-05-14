# Phase 2 — Screen-build agent briefs (ready to dispatch)

These are the prompts I'll feed into Agent tool calls once Phase 1 verifies green.

## Common header (prepended to all)

```
You are a senior developer porting an EXISTING HTML/JSX prototype to a real Next.js 15 / React 19 / TypeScript / Tailwind app. Work autonomously — no clarifying questions.

REPO: /home/claude/K-12_AI_tutorApp
PROTOTYPE: /home/claude/repo/project/   (read these to match the design EXACTLY)
ALREADY DONE: monorepo, design tokens in tailwind.config.ts, shared components (AriaMascot, Icon, TopNav, Rail, CourseCard) in apps/web/src/components/aria/, lib/api.ts, lib/supabase/*, FastAPI backend stubs returning sample data.

RULES:
- Use 'use client' only on interactive components (forms, animations, hooks).
- All Tailwind classes; no hardcoded hex colors (the tokens are: paper, paper-2, ink, ink-2, ink-3, indigo, indigo-deep, indigo-soft, coral, coral-soft, amber, amber-soft, mint, mint-soft, lavender, lavender-soft, board, board-2, chalk, chalk-blue/yellow/pink/green/coral).
- Fonts via Tailwind: font-display (Bricolage Grotesque), font-body (DM Sans), font-mono (JetBrains Mono).
- Framer Motion for animations, not raw CSS @keyframes.
- All API calls via lib/api.ts; for now backend returns mock data, so just point at /v1/... and let it work.
- TypeScript strict. Run pnpm typecheck before finishing.
- shadcn/ui already installed; use Button, Input, Card components where appropriate.

WHEN STUCK:
- Read the source JSX carefully — every detail in the prototype is intentional.
- Don't over-engineer. Match what's there.
- If a piece of the prototype uses an inline ::after CSS pseudo-element trick, replicate it.

DELIVER:
1. The files specified
2. `pnpm typecheck` exit 0
3. `pnpm lint` exit 0 (warnings OK, no errors)
4. A short report listing files + any judgment calls made
```

## Agent S1 — Marketing (Landing + Onboarding)

```
[common header]

YOUR SCOPE: apps/web/src/app/page.tsx (Landing) + apps/web/src/app/(marketing)/onboarding/page.tsx + supporting components in apps/web/src/components/marketing/

REFERENCE: /home/claude/repo/project/screens-marketing.jsx (both LandingScreen and OnboardingScreen are defined here).

PORT:
1. LandingScreen → Server Component at apps/web/src/app/page.tsx
   - Use the exact hero structure: left text column, right chalkboard mock
   - Include the live mini-chalkboard SVG with the wave + amplitude + wavelength markers (it's an SVG with feTurbulence filter for chalk effect — copy verbatim)
   - "Watch demo" nav button → router.push('/classroom/demo')
   - "Start free" CTA → router.push('/onboarding')
   - Floating feature chips (f1/f2/f3 styled badges)
   - Trust avatars row
   - 4-column features strip at bottom

2. OnboardingScreen → Client Component at apps/web/src/app/(marketing)/onboarding/page.tsx
   - 4-step flow: meet Aria → grade → courses → goal
   - useState for step, grade, courses[], goal
   - Progress bar at top with 4 segments
   - Each step uses the .ob-opt button styling from styles.css
   - Final step → router.push('/dashboard')

ADDITIONAL: Add a route group (marketing) at apps/web/src/app/(marketing)/ with its own layout.tsx that DOES NOT include the TopNav/Rail (since landing has its own minimal nav).

VERIFY: Visit http://localhost:3000 and /onboarding — both render without error.
```

## Agent S2 — In-app screens (Dashboard, Planner, Notes, History)

```
[common header]

YOUR SCOPE: 
- apps/web/src/app/(app)/layout.tsx — wraps with TopNav + Rail
- apps/web/src/app/(app)/dashboard/page.tsx
- apps/web/src/app/(app)/planner/page.tsx
- apps/web/src/app/(app)/notes/page.tsx
- apps/web/src/app/(app)/history/page.tsx
- Supporting components in apps/web/src/components/dashboard/

REFERENCE: /home/claude/repo/project/screens-dashboard.jsx (all four screens defined here, ~400 lines).

PORT each screen verbatim. For data, hardcode the same arrays the prototype uses (courses, units, today's schedule, notes, decks, history rows). Later we'll wire to /v1/* via TanStack Query — for now use static data so screens render.

NOTES SCREEN: tabbed Notes / Flashcards. Use shadcn Tabs.

HISTORY SCREEN: chalk-style thumbnails — port the small SVG generator from the prototype.

PLANNER SCREEN: 7-day calendar with color-coded blocks (mint/indigo/amber/coral/lavender variants). Sidebar with goals + Aria's note card + weekly stats.

VERIFY: All 4 routes render. Navigation between them via Rail works.
```

## Agent S3 — Classroom + Q&A + Quiz + Complete (THE CORE)

```
[common header]

YOUR SCOPE: 
- apps/web/src/app/classroom/[topicId]/page.tsx — the live lesson
- apps/web/src/app/classroom/quiz/[topicId]/page.tsx — quiz screen
- apps/web/src/app/classroom/complete/[sessionId]/page.tsx — completion
- apps/web/src/components/classroom/* — sketch layer, voice mode, reactions cluster, reply bar, peer presence, whiteboard SVG, Q&A overlay, sketch toolbar, quiz-me-now pop, caption bar

REFERENCE FILES (READ ALL OF THEM):
- /home/claude/repo/project/screens-classroom.jsx (~500 lines — ClassroomScreen, QAOverlay, QuizScreen, CompleteScreen)
- /home/claude/repo/project/whiteboard.jsx (~160 lines — 8-step WhiteboardSVG + QAAnswerSVG)
- /home/claude/repo/project/tutor-features.jsx (~450 lines — SketchLayer, SketchToolbar, useSocraticAria, ConfidenceCheck (omit), QuizMePop, PeerPresence, recognizeStroke, ReplyBar)
- /home/claude/repo/project/voice-features.jsx (~260 lines — useSpeak, useListen, VoiceMode, ReactionsCluster, PaceControl (omit), VoiceBar)
- /home/claude/repo/project/styles.css — classroom-specific styles (.classroom, .cr-*, .qa-*, .vm-*, .sketch-*, .reply-bar etc.)

KEY DETAILS:
- ClassroomScreen has many sub-systems: lesson auto-advance, sketch mode toggle, voice mode toggle, Q&A overlay, quiz interrupt, reactions, reply bar, sidebar outline.
- The "Socratic Aria" caption updates contextually based on recognized sketch shape OR student reply OR hints.
- All the prototype's hooks (useSpeak, useListen, useSocraticAria) should be ported as separate hook files in apps/web/src/hooks/.
- The WhiteboardSVG renders 8 chalk steps with SVG <feTurbulence> filter — port verbatim, just convert to JSX/TSX.
- SketchLayer uses pointer events + an SVG with createSVGPoint for coords. Use perfect-freehand for prettier strokes (replace the prototype's simple polyline path with perfect-freehand smoothed strokes).
- VoiceMode currently uses browser SpeechRecognition; KEEP that as the fallback UI, but add a separate code path that opens a WS to /v1/sessions/:id/voice for real Gemini Live integration (the WS handler is a stub but the connection should work; Agent A3 will fill in the bridge).
- ReplyBar submits text reply, also has a mic button that opens VoiceMode.

INTEGRATION:
- POST /v1/sessions/{topicId} to start a session on classroom mount — get sessionId from response.
- For Q&A: POST /v1/sessions/{sessionId}/qa with body {q_text, source: 'text'} — consume SSE stream, append "delta" events to caption.
- For sketch: on every stroke complete, send it as PNG (canvas.toDataURL) to /v1/sessions/{sessionId}/sketch with form-data {image, question, current_step_idx} — consume SSE stream.
- For reply: POST /v1/sessions/{sessionId}/reply {text} — consume SSE.
- For reaction: POST /v1/sessions/{sessionId}/reaction {reaction}.

PORT BUT REMOVE per user feedback in the chat transcript:
- PaceControl (🐢/1×/🐇 buttons)
- ConfidenceCheck (the 1-5 floater)

KEEP per user feedback:
- Sketch with Socratic Aria
- Quiz me now
- Peer presence
- Reply bar
- Voice mode

VERIFY: 
- /classroom/wave-properties-anatomy renders with WhiteboardSVG visible
- Clicking "Raise hand" opens Q&A overlay
- Clicking ✏️ enters sketch mode, can draw
- Clicking ⚡ opens Quiz Me Pop
- Reactions cluster on left works
- Reply bar at bottom works (UI-wise; API call happens but mock data returned)
```

## Verifier V2

```
Run pnpm dev. Visit every page. Walk through the user flow:
- / → click "Start free" → /onboarding → complete → /dashboard
- /dashboard → click resume card → /classroom/wave-properties-anatomy
- In classroom: try sketch, try Q&A, try reaction, try voice button (UI only)
- Navigate via Rail to planner, notes, history
- Open /classroom/quiz/wave-properties-anatomy
- Open /classroom/complete/test

Capture any console errors, broken navigations, or missing styles. Report a punch list.
```
