# @edumind/web

Next.js 15 frontend for the EduMind K-12 AI tutor.

## Stack

- Next.js 15 (App Router, Turbopack) on React 19
- Tailwind CSS 3.4 + custom design tokens (see `tailwind.config.ts`)
- Supabase auth via `@supabase/ssr`
- TanStack Query for server state, Zustand for client state
- Vercel AI SDK for streaming responses, sonner for toasts
- Vitest (unit) + Playwright (e2e)

## Setup

```bash
pnpm install
cp ../../.env.example .env.local   # if you haven't already
```

Required env vars (in `.env.local`):

- `NEXT_PUBLIC_API_BASE` — FastAPI backend URL (default `http://localhost:8000`)
- `NEXT_PUBLIC_SUPABASE_URL` — Supabase project URL
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` — Supabase anon public key

## Scripts

| Command            | What it does                                  |
| ------------------ | --------------------------------------------- |
| `pnpm dev`         | Start dev server on http://localhost:3000     |
| `pnpm build`       | Production build                              |
| `pnpm start`       | Run the production build                      |
| `pnpm typecheck`   | `tsc --noEmit`                                |
| `pnpm lint`        | `next lint`                                   |
| `pnpm test`        | Vitest unit suite                             |
| `pnpm test:watch`  | Vitest in watch mode                          |
| `pnpm test:e2e`    | Playwright e2e (auto-starts `pnpm dev`)       |

## Layout

```
src/
├── app/                  # Next App Router (pages live here)
├── components/
│   ├── aria/             # Mascot, Icon, TopNav, Rail, CourseCard
│   └── providers.tsx     # React Query + Supabase + toasts
└── lib/
    ├── api.ts            # Typed fetch wrapper → NEXT_PUBLIC_API_BASE
    ├── supabase/
    │   ├── client.ts     # browser client (singleton)
    │   └── server.ts     # request-bound server client
    └── utils.ts          # `cn()` helper (clsx + tailwind-merge)
```

The visual reference for every screen lives in `../../../repo/project/`.
