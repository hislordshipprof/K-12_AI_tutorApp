import Link from 'next/link';

import { Icon } from '@/components/aria/icon';
import { TopNav } from '@/components/aria/top-nav';
import { FloatingChip } from '@/components/marketing/floating-chip';
import { LiveBoard } from '@/components/marketing/live-board';

/**
 * Resolve the "watch a lesson" demo link to a real seeded topic UUID.
 *
 * The marketing CTAs used to point at the `wave-properties-anatomy`
 * prototype slug, which has no `topics` row — opening it failed the
 * session FK. We resolve the first real AP Physics 1 topic server-side so
 * the demo always lands on a real DB topic.
 */
async function resolveDemoClassroomHref(): Promise<string | null> {
  const apiBase =
    process.env.NEXT_PUBLIC_API_BASE ?? process.env.API_BASE_URL ?? '';
  if (!apiBase) return null;
  try {
    const res = await fetch(`${apiBase}/v1/courses/ap-physics-1/units`, {
      cache: 'no-store',
    });
    if (!res.ok) return null;
    const units = (await res.json()) as {
      topics: { id: string }[];
    }[];
    for (const unit of units) {
      const topic = unit.topics?.[0];
      if (topic?.id) return `/classroom/${topic.id}`;
    }
  } catch {
    // Network blip — fall through to null.
  }
  return null;
}

/**
 * Landing screen — ported from prototype `LandingScreen` in
 * `screens-marketing.jsx`. Server-rendered: the only "interactive"
 * pieces are the TopNav (a client island) and the framer-motion-less
 * floating chips/board which use plain CSS animations from Tailwind.
 */
export default async function HomePage() {
  // Demo CTAs route to a real seeded topic; when the curriculum can't be
  // reached we send the visitor to onboarding rather than a dead lesson.
  const demoHref = (await resolveDemoClassroomHref()) ?? '/onboarding';

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-paper">
      <TopNav
        streak={0}
        right={
          <Link
            href={demoHref}
            className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[10px] border-[1.5px] border-border-2 bg-transparent px-3.5 py-2 text-[13px] font-semibold text-ink transition-colors hover:border-ink-3 hover:bg-ink/[0.04]"
          >
            Watch demo
          </Link>
        }
      />

      <main className="relative flex-1 overflow-y-auto overflow-x-hidden bg-paper">
        {/* gradient blobs */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse 60% 50% at 85% 15%, rgba(91,91,229,.10) 0%, transparent 60%), radial-gradient(ellipse 50% 50% at 10% 85%, rgba(255,122,89,.08) 0%, transparent 60%)',
          }}
        />
        {/* subtle dotted grid w/ radial mask */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              'linear-gradient(rgba(27,31,46,.04) 1px, transparent 1px), linear-gradient(90deg, rgba(27,31,46,.04) 1px, transparent 1px)',
            backgroundSize: '32px 32px',
            maskImage:
              'radial-gradient(ellipse 60% 60% at 50% 45%, #000 0%, transparent 90%)',
            WebkitMaskImage:
              'radial-gradient(ellipse 60% 60% at 50% 45%, #000 0%, transparent 90%)',
          }}
        />

        {/* HERO */}
        <section className="relative z-[1] mx-auto grid min-h-[calc(100vh-64px)] max-w-[1200px] grid-cols-1 items-center gap-8 px-7 py-8 md:gap-[60px] md:py-[60px] md:pb-[100px] lg:grid-cols-[1.05fr_1fr]">
          {/* LEFT */}
          <div>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-border-2 bg-white px-3.5 py-1.5 text-[13px] font-semibold text-ink-2 shadow-sm">
              <span className="h-2 w-2 animate-soft-pulse rounded-full bg-mint shadow-[0_0_0_3px_rgba(52,201,122,0.2)]" />
              AI Classroom · Beta
            </div>

            <h1 className="mb-6 font-display text-[clamp(44px,5.5vw,68px)] font-bold leading-[1.05] tracking-[-0.035em] text-ink">
              Like having a
              <br />
              <span className="text-indigo">private tutor</span>,
              <br />
              <span className="relative inline-block whitespace-nowrap text-ink">
                24 / 7.
                <span
                  aria-hidden
                  className="absolute -left-[3%] -right-[3%] bottom-[6%] -z-10 h-[18%] -skew-x-[8deg] rounded-md bg-amber opacity-50"
                />
              </span>
            </h1>

            <p className="mb-8 max-w-[520px] text-[19px] leading-[1.55] text-ink-2">
              Prof. Aria teaches live &mdash; voice, whiteboard, the whole
              thing. Ask anything anytime, she pauses and{' '}
              <b className="font-bold">draws the answer</b> right where
              you&apos;re looking. Then picks up exactly where she left off.
            </p>

            <div className="mb-9 flex flex-wrap gap-3">
              <Link
                href="/onboarding"
                className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-2xl bg-indigo px-7 py-4 text-base font-semibold text-white shadow-[0_4px_14px_rgba(91,91,229,.32),inset_0_-2px_0_rgba(0,0,0,.18)] transition-all duration-200 hover:-translate-y-px hover:bg-indigo-deep active:scale-[0.97]"
              >
                Start free <Icon name="arrow" size={18} />
              </Link>
              <Link
                href={demoHref}
                className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-2xl border-[1.5px] border-border-2 bg-transparent px-7 py-4 text-base font-semibold text-ink transition-all duration-200 hover:border-ink-3 hover:bg-ink/[0.04] active:scale-[0.97]"
              >
                Watch a 90-sec lesson
              </Link>
            </div>

            <div className="flex items-center gap-[18px] text-[13px] text-ink-3">
              <span>
                Free during beta · No credit card · Cancel anytime
              </span>
            </div>
          </div>

          {/* RIGHT — board mock + floating chips */}
          <div className="relative">
            <LiveBoard />
            <FloatingChip
              icon="hand"
              label="Raise hand"
              toneClassName="text-mint"
              iconBgClassName="bg-mint"
              positionClassName="top-[30px] -left-10"
              delaySeconds={0}
            />
            <FloatingChip
              icon="sparkle"
              label="Smart Q&A"
              toneClassName="text-indigo"
              iconBgClassName="bg-indigo"
              positionClassName="bottom-20 -right-10"
              delaySeconds={1.4}
            />
            <FloatingChip
              icon="voice"
              label="Voice teacher"
              toneClassName="text-coral"
              iconBgClassName="bg-coral"
              positionClassName="top-1/2 -left-[60px]"
              delaySeconds={2.6}
            />
          </div>
        </section>

        {/* FEATURES STRIP */}
        <section className="relative z-[1] mx-auto max-w-[1240px] px-7 pb-20">
          <div className="grid grid-cols-2 gap-6 border-t border-border py-8 md:grid-cols-4">
            <div className="flex flex-col gap-2">
              <div className="font-display text-[34px] font-bold leading-none tracking-[-0.03em] text-ink">
                <em className="not-italic text-indigo">24/7</em>
              </div>
              <div className="text-[13px] leading-[1.4] text-ink-3">
                Aria&apos;s always in class. No scheduling, no wait.
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <div className="font-display text-[34px] font-bold leading-none tracking-[-0.03em] text-ink">
                3 <em className="not-italic text-indigo">APs</em>
              </div>
              <div className="text-[13px] leading-[1.4] text-ink-3">
                Physics 1, Calc BC, Biology — aligned to the 2024 CEDs.
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <div className="font-display text-[34px] font-bold leading-none tracking-[-0.03em] text-ink">
                ∞
              </div>
              <div className="text-[13px] leading-[1.4] text-ink-3">
                Ask anything. She&apos;ll draw a chalk diagram and explain.
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <div className="font-display text-[34px] font-bold leading-none tracking-[-0.03em] text-ink">
                $0
              </div>
              <div className="text-[13px] leading-[1.4] text-ink-3">
                Free during beta. No card. No catch.
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
