'use client';

import { useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { DeckRow } from '@/components/dashboard/deck-row';
import { NoteCard, type NoteColor } from '@/components/dashboard/note-card';
import { cn } from '@/lib/utils';

interface NoteData {
  c: NoteColor;
  tag: string;
  t: string;
  b: React.ReactNode;
  d: string;
}

const NOTES: NoteData[] = [
  {
    c: 'amber',
    tag: 'Aria · Pinned',
    t: 'The wave equation, in plain English',
    b: (
      <>
        If you only remember one thing: <code>v = f · λ</code>. Speed equals how
        often a wave hits times how far apart the hits are. Frequency up →
        wavelength down. Always.
      </>
    ),
    d: 'Today · auto-generated',
  },
  {
    c: 'indigo',
    tag: 'You',
    t: 'Why amplitude ≠ wavelength',
    b: 'Amplitude is the HEIGHT of the wave (energy). Wavelength is the LENGTH of one full cycle (distance). I keep mixing them up on the diagrams.',
    d: 'May 12',
  },
  {
    c: '',
    tag: 'Aria',
    t: 'Crest vs Trough — quick reference',
    b: 'Crest = highest point above rest. Trough = lowest point below rest. Distance between two adjacent crests = one wavelength.',
    d: 'May 11',
  },
  {
    c: 'mint',
    tag: 'Aria · Q&A',
    t: '"What does period mean again?"',
    b: 'Period (T) is the TIME for one full cycle. Measured in seconds. It is the inverse of frequency: T = 1/f. So a 4 Hz wave has T = 0.25s.',
    d: 'May 10 · from your question',
  },
  {
    c: 'coral',
    tag: 'You',
    t: 'AP exam tip — Aria said',
    b: "On any \"find v\" problem, write down what you know first. Frequency? Wavelength? Then v = fλ. Don't guess units.",
    d: 'May 9',
  },
  {
    c: '',
    tag: 'Aria',
    t: 'Position, Velocity, Acceleration',
    b: 'Three layers. Position is WHERE. Velocity is how fast position changes. Acceleration is how fast velocity changes. Each one is the slope of the one above.',
    d: 'May 8',
  },
  {
    c: 'lav',
    tag: 'Aria · Pinned',
    t: "Newton's 3rd Law misconception",
    b: "Equal & opposite forces act on DIFFERENT objects, never the same one. That's why they don't cancel.",
    d: 'May 5',
  },
  {
    c: '',
    tag: 'You',
    t: 'Kinematic equations cheat sheet',
    b: 'v = u + at · s = ut + ½at² · v² = u² + 2as · s = (u+v)/2 · t. Remember which variable is missing from each.',
    d: 'May 3',
  },
  {
    c: 'amber',
    tag: 'Aria',
    t: 'Projectile motion — split it',
    b: 'Horizontal and vertical are INDEPENDENT. Same time of flight. Horizontal: constant v. Vertical: gravity does all the work.',
    d: 'May 1',
  },
];

const DECKS = [
  { t: 'Wave Anatomy', count: 22, due: 8, m: 92 },
  { t: 'Kinematics core terms', count: 30, due: 0, m: 100 },
  { t: "Newton's Laws — common traps", count: 18, due: 5, m: 78 },
  { t: 'Energy & Work', count: 24, due: 12, m: 65 },
  { t: 'Greek letters & symbols', count: 16, due: 0, m: 88 },
  { t: 'AP FRQ command words', count: 12, due: 3, m: 70 },
];

export default function NotesPage() {
  const [tab, setTab] = useState<'notes' | 'cards'>('notes');

  return (
    <div className="mx-auto max-w-[1180px] px-8 pb-20 pt-8">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="font-display text-4xl font-bold tracking-[-0.03em]">
            Notebook
          </div>
          <div className="mt-1 text-sm text-ink-3">
            Aria saves the key idea from every lesson + every question you ask.
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex gap-1 rounded-xl bg-paper-2 p-1">
            <button
              type="button"
              onClick={() => setTab('notes')}
              className={cn(
                'rounded-lg px-4 py-2 text-[13px] font-semibold transition-colors',
                tab === 'notes'
                  ? 'bg-white text-ink shadow-sm'
                  : 'text-ink-3',
              )}
            >
              Notes{' '}
              <b className="font-bold tabular-nums">42</b>
            </button>
            <button
              type="button"
              onClick={() => setTab('cards')}
              className={cn(
                'rounded-lg px-4 py-2 text-[13px] font-semibold transition-colors',
                tab === 'cards'
                  ? 'bg-white text-ink shadow-sm'
                  : 'text-ink-3',
              )}
            >
              Flashcards <b className="font-bold">6</b>
            </button>
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-[10px] bg-ink px-3.5 py-2 text-[13px] font-semibold text-white transition-all hover:-translate-y-px hover:bg-black"
          >
            <Icon name="plus" size={14} /> New
          </button>
        </div>
      </div>

      {tab === 'notes' && (
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {NOTES.map((n, i) => (
            <NoteCard
              key={i}
              color={n.c}
              tag={n.tag}
              title={n.t}
              body={n.b}
              date={n.d}
            />
          ))}
        </div>
      )}

      {tab === 'cards' && (
        <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2">
          {DECKS.map((d, i) => (
            <DeckRow
              key={i}
              title={d.t}
              count={d.count}
              due={d.due}
              mastery={d.m}
            />
          ))}
        </div>
      )}
    </div>
  );
}
