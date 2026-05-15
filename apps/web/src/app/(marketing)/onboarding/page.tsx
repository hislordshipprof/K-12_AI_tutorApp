'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { AriaMascot } from '@/components/aria/aria-mascot';
import { Icon } from '@/components/aria/icon';
import { TopNav } from '@/components/aria/top-nav';
import { cn } from '@/lib/utils';

const GRADES = [
  { label: '9th grade', emoji: '📗' },
  { label: '10th grade', emoji: '📘' },
  { label: '11th grade', emoji: '📙' },
  { label: '12th grade', emoji: '📕' },
  { label: 'Homeschool', emoji: '🏠' },
  { label: 'Just curious', emoji: '✨' },
] as const;

const COURSES = [
  { name: 'AP Physics 1', slug: 'ap-physics-1', emoji: '⚛️', desc: 'Mechanics, waves, electricity' },
  { name: 'AP Calculus BC', slug: 'ap-calc-bc', emoji: '∫', desc: 'Derivatives, integrals, series' },
  { name: 'AP Biology', slug: 'ap-biology', emoji: '🧬', desc: 'Cells, genetics, evolution' },
  // The next three don't have seeded content yet — selecting them still records
  // the preference, but the dashboard will fall back to whichever course
  // actually has data for the curriculum tree.
  { name: 'AP Chemistry', slug: 'ap-chemistry', emoji: '🧪', desc: 'Atoms, reactions, equilibrium' },
  { name: 'AP Statistics', slug: 'ap-statistics', emoji: '📊', desc: 'Probability, inference' },
  { name: 'AP CS A', slug: 'ap-cs-a', emoji: '💻', desc: 'Java, algorithms, OOP' },
] as const;

const ONBOARDING_KEY = 'edumind.onboarding';
interface OnboardingPrefs {
  grade?: string;
  courses?: string[];      // display names
  primarySlug?: string;    // first selected course's slug — used by dashboard
  goal?: string;
}

const GOALS = [
  {
    name: 'Score a 5 on the AP exam',
    desc: 'Heavy practice, FRQ training, hardest problems',
    emoji: '🏆',
  },
  {
    name: 'Pass the class with an A',
    desc: 'Steady pacing, balanced theory + practice',
    emoji: '⭐',
  },
  {
    name: 'Just understand the material',
    desc: 'Slower pace, more intuition, fewer drills',
    emoji: '💡',
  },
  {
    name: 'Catch up after falling behind',
    desc: 'Foundation-first, prereqs included',
    emoji: '🚀',
  },
] as const;

/**
 * Tailwind classes mirroring the prototype's `.ob-opt` rules. Selected
 * state swaps the border to indigo and the bg to indigo-soft, and the
 * check circle fills indigo with a ✓ pseudo-element rendered via a real
 * `<span>` here (Tailwind cannot apply `::after` content).
 */
function OptionButton({
  emoji,
  title,
  description,
  selected,
  onClick,
}: {
  emoji: string;
  title: string;
  description?: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-3.5 rounded-2xl border-2 bg-white p-[18px] text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-ink-3 hover:shadow-md',
        selected
          ? 'border-indigo bg-indigo-soft'
          : 'border-border',
      )}
    >
      <div
        className={cn(
          'grid h-[46px] w-[46px] flex-shrink-0 place-items-center rounded-xl text-[22px] transition-colors',
          selected ? 'bg-white shadow-sm' : 'bg-paper-2',
        )}
      >
        {emoji}
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 text-[15px] font-semibold text-ink">{title}</div>
        {description && (
          <div className="text-[13px] leading-[1.4] text-ink-3">
            {description}
          </div>
        )}
      </div>
      <div
        className={cn(
          'grid h-[22px] w-[22px] flex-shrink-0 place-items-center rounded-full border-2 text-[12px] text-white transition-colors',
          selected
            ? 'border-indigo bg-indigo'
            : 'border-border-2 bg-transparent',
        )}
      >
        {selected ? '✓' : ''}
      </div>
    </button>
  );
}

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [grade, setGrade] = useState<string | null>(null);
  const [courses, setCourses] = useState<string[]>([]);
  const [goal, setGoal] = useState<string | null>(null);

  // Persist onboarding choices to localStorage so the dashboard can
  // honour the course selection instead of always showing Physics.
  const persist = (patch: Partial<OnboardingPrefs>) => {
    try {
      const existing: OnboardingPrefs = JSON.parse(
        window.localStorage.getItem(ONBOARDING_KEY) ?? '{}',
      );
      const next: OnboardingPrefs = { ...existing, ...patch };
      // Resolve primarySlug from the first selected course's display name.
      if (next.courses && next.courses.length > 0) {
        const first = COURSES.find((c) => c.name === next.courses![0]);
        if (first) next.primarySlug = first.slug;
      }
      window.localStorage.setItem(ONBOARDING_KEY, JSON.stringify(next));
    } catch {
      // localStorage unavailable (private mode, SSR) — just drop the write.
    }
  };

  const next = () => {
    // Snapshot current selections to localStorage at each step so a
    // browser refresh doesn't wipe the choices the student already made.
    persist({ grade: grade ?? undefined, courses, goal: goal ?? undefined });
    if (step === 3) {
      router.push('/dashboard');
      return;
    }
    setStep((s) => s + 1);
  };
  const back = () => setStep((s) => Math.max(0, s - 1));

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-paper">
      <TopNav streak={0} />

      <main
        className="relative h-[calc(100vh-64px)] overflow-hidden"
        style={{
          background:
            'linear-gradient(180deg, var(--paper) 0%, #FFF7E8 100%)',
        }}
      >
        <div className="mx-auto flex h-full max-w-[680px] flex-col px-7 py-12">
          {/* Progress dots */}
          <div className="mb-10 flex gap-2">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className={cn(
                  'h-1.5 flex-1 rounded-[3px] transition-colors duration-300',
                  step > i
                    ? 'bg-mint'
                    : step === i
                      ? 'bg-ink'
                      : 'bg-ink/[0.08]',
                )}
              />
            ))}
          </div>

          {/* Step content */}
          <div className="flex flex-1 flex-col justify-center">
            {step === 0 && (
              <div className="flex flex-col items-center py-5 text-center">
                <div className="mb-6">
                  <AriaMascot size={140} pulse withRing />
                </div>
                <div className="mt-7 whitespace-nowrap text-center text-[13px] font-bold uppercase tracking-[0.15em] text-indigo">
                  👋 &nbsp;Meet your tutor
                </div>
                <h1 className="mb-[18px] mt-3.5 text-center font-display text-[42px] font-bold leading-[1.05] tracking-[-0.03em]">
                  Hi, I&apos;m{' '}
                  <span className="italic text-indigo">Aria.</span>
                </h1>
                <p className="mb-8 max-w-[480px] text-center text-[17px] leading-[1.5] text-ink-2">
                  I&apos;ll teach you live &mdash; speaking, drawing on the
                  whiteboard, answering whatever you throw at me. First, three
                  quick questions so I know how to teach you.
                </p>
                <button
                  type="button"
                  onClick={next}
                  className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-2xl bg-indigo px-7 py-4 text-base font-semibold text-white shadow-[0_4px_14px_rgba(91,91,229,.32),inset_0_-2px_0_rgba(0,0,0,.18)] transition-all duration-200 hover:-translate-y-px hover:bg-indigo-deep active:scale-[0.97]"
                >
                  Let&apos;s go <Icon name="arrow" size={18} />
                </button>
              </div>
            )}

            {step === 1 && (
              <div>
                <div className="mb-3.5 text-[13px] font-bold uppercase tracking-[0.15em] text-indigo">
                  Step 1 of 3
                </div>
                <h1 className="mb-3.5 font-display text-[42px] font-bold leading-[1.05] tracking-[-0.03em]">
                  What grade are you in?
                </h1>
                <p className="mb-8 max-w-[540px] text-[17px] leading-[1.5] text-ink-2">
                  So I can match the pace and skip stuff you already know.
                </p>
                <div className="mb-7 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {GRADES.map(({ label, emoji }) => (
                    <OptionButton
                      key={label}
                      emoji={emoji}
                      title={label}
                      selected={grade === label}
                      onClick={() => setGrade(label)}
                    />
                  ))}
                </div>
                <Nav
                  onBack={back}
                  onNext={next}
                  disabled={!grade}
                  nextLabel="Continue"
                />
              </div>
            )}

            {step === 2 && (
              <div>
                <div className="mb-3.5 text-[13px] font-bold uppercase tracking-[0.15em] text-indigo">
                  Step 2 of 3
                </div>
                <h1 className="mb-3.5 font-display text-[42px] font-bold leading-[1.05] tracking-[-0.03em]">
                  Which courses?
                </h1>
                <p className="mb-8 max-w-[540px] text-[17px] leading-[1.5] text-ink-2">
                  Pick everything you&apos;re studying. You can change this
                  later.
                </p>
                <div className="mb-7 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {COURSES.map((c) => {
                    const on = courses.includes(c.name);
                    return (
                      <OptionButton
                        key={c.name}
                        emoji={c.emoji}
                        title={c.name}
                        description={c.desc}
                        selected={on}
                        onClick={() =>
                          setCourses((prev) =>
                            on
                              ? prev.filter((x) => x !== c.name)
                              : [...prev, c.name],
                          )
                        }
                      />
                    );
                  })}
                </div>
                <Nav
                  onBack={back}
                  onNext={next}
                  disabled={courses.length === 0}
                  nextLabel={
                    courses.length
                      ? `Continue with ${courses.length}`
                      : 'Pick at least one'
                  }
                />
              </div>
            )}

            {step === 3 && (
              <div>
                <div className="mb-3.5 text-[13px] font-bold uppercase tracking-[0.15em] text-indigo">
                  Step 3 of 3
                </div>
                <h1 className="mb-3.5 font-display text-[42px] font-bold leading-[1.05] tracking-[-0.03em]">
                  What&apos;s your goal?
                </h1>
                <p className="mb-8 max-w-[540px] text-[17px] leading-[1.5] text-ink-2">
                  Aria adjusts difficulty + practice volume based on this.
                </p>
                <div className="mb-7 grid grid-cols-1 gap-3">
                  {GOALS.map((g) => (
                    <OptionButton
                      key={g.name}
                      emoji={g.emoji}
                      title={g.name}
                      description={g.desc}
                      selected={goal === g.name}
                      onClick={() => setGoal(g.name)}
                    />
                  ))}
                </div>
                <Nav
                  onBack={back}
                  onNext={next}
                  disabled={!goal}
                  nextLabel="Open my classroom"
                  variant="coral"
                />
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

function Nav({
  onBack,
  onNext,
  disabled,
  nextLabel,
  variant = 'primary',
}: {
  onBack: () => void;
  onNext: () => void;
  disabled: boolean;
  nextLabel: string;
  variant?: 'primary' | 'coral';
}) {
  return (
    <div className="mt-auto flex items-center justify-between pt-6">
      <button
        type="button"
        onClick={onBack}
        className="cursor-pointer text-sm font-medium text-ink-3 transition-colors hover:text-ink"
      >
        ← Back
      </button>
      <button
        type="button"
        onClick={onNext}
        disabled={disabled}
        className={cn(
          'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-2xl px-7 py-4 text-base font-semibold text-white transition-all duration-200 active:scale-[0.97]',
          variant === 'coral'
            ? 'bg-coral shadow-[0_4px_14px_rgba(255,122,89,.32),inset_0_-2px_0_rgba(0,0,0,.18)] hover:-translate-y-px hover:bg-[#FF5C36]'
            : 'bg-ink shadow-[0_4px_14px_rgba(27,31,46,.18),inset_0_-2px_0_rgba(0,0,0,.18)] hover:-translate-y-px hover:bg-black',
          disabled && 'cursor-not-allowed opacity-40 hover:translate-y-0',
        )}
      >
        {nextLabel} <Icon name="arrow" size={16} />
      </button>
    </div>
  );
}
