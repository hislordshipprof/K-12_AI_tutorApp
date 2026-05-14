# Screen specs (for Phase 2 agents)

The prototype lives at `/home/claude/repo/project/`. Read the JSX + CSS to match the visual design exactly. Port to React/TS/Tailwind with Next.js App Router conventions.

## Path layout

```
apps/web/src/app/
  page.tsx                              # Landing
  (marketing)/
    onboarding/page.tsx
  (app)/
    layout.tsx                          # TopNav + Rail wrapper
    dashboard/page.tsx
    planner/page.tsx
    notes/page.tsx
    history/page.tsx
  classroom/
    [topicId]/page.tsx                  # Live lesson
    quiz/[topicId]/page.tsx
    complete/[sessionId]/page.tsx
  api/                                  # BFF (auth callback etc.)
    auth/callback/route.ts
```

## Shared components (already ported in scaffolding phase)

`apps/web/src/components/aria/`
- `aria-mascot.tsx` — the indigo orb with eyes
- `icon.tsx` — custom-stroked icon set
- `top-nav.tsx` — header with logo, breadcrumb, streak, avatar
- `rail.tsx` — left vertical app rail (Home, Plan, Notes, History, Resume, Settings)
- `course-card.tsx`

## Source-of-truth files

| Screen | Prototype JSX |
|---|---|
| Landing | `screens-marketing.jsx` LandingScreen |
| Onboarding | `screens-marketing.jsx` OnboardingScreen |
| Dashboard | `screens-dashboard.jsx` DashboardScreen |
| Planner | `screens-dashboard.jsx` PlannerScreen |
| Notes & Flashcards | `screens-dashboard.jsx` NotesScreen |
| History | `screens-dashboard.jsx` HistoryScreen |
| Classroom | `screens-classroom.jsx` ClassroomScreen + WhiteboardSVG |
| Q&A overlay | `screens-classroom.jsx` QAOverlay |
| Quiz | `screens-classroom.jsx` QuizScreen |
| Complete | `screens-classroom.jsx` CompleteScreen |
| Sketch / voice / reactions | `tutor-features.jsx`, `voice-features.jsx`, `whiteboard.jsx` |

## Conventions

- Use Server Components by default; mark Client Components with `'use client'`
- All screens must work without auth at first (use mock data via TanStack Query that points at `/v1/...` with a fallback to static JSON)
- All API calls go through `lib/api.ts`
- All forms use React Hook Form + Zod
- All animations via Framer Motion (port from CSS `@keyframes` where needed)
- Responsive: desktop-first per the prototype; mobile breakpoints follow Tailwind defaults
- Color tokens via Tailwind classes (`bg-indigo`, `text-coral`, etc.), NOT hardcoded hexes

## Open data needs (mock for now)

Each screen needs example data the agent should hardcode locally OR fetch from the API. Use the prototype's hardcoded data verbatim as the mock — the dashboard's course list, lesson steps, schedule items, notes, etc. are all in the prototype JSX.

## Acceptance per screen

Visual diff against the prototype is the bar. After porting:
1. `pnpm dev` and visit the page — visually matches the prototype within reason
2. `pnpm typecheck` and `pnpm lint` clean
3. Navigation links work
4. A Playwright smoke test loads the page and finds key text/elements
