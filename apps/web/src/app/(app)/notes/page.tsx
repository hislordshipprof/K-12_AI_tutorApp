'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { DeckRow } from '@/components/dashboard/deck-row';
import { NoteCard, type NoteColor } from '@/components/dashboard/note-card';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

interface NoteRow {
  id: string;
  kind: 'auto' | 'user' | 'qa' | 'aria';
  title: string | null;
  body: string | null;
  color: NoteColor | string | null;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

interface FlashcardRow {
  id: string;
  deck_id: string;
  front: string;
  due_at: string;
}

function tagFor(n: NoteRow): string {
  const who = n.kind === 'user' ? 'You' : 'Aria';
  return n.pinned ? `${who} · Pinned` : who;
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

export default function NotesPage() {
  const [tab, setTab] = useState<'notes' | 'cards'>('notes');

  const { data: notes = [], isLoading: notesLoading } = useQuery<NoteRow[]>({
    queryKey: ['notes'],
    queryFn: async () => {
      try {
        return await api<NoteRow[]>('/v1/notes');
      } catch {
        return [];
      }
    },
    staleTime: 30_000,
  });

  // Flashcards/due gives the cards that need review now; group by deck client-side.
  const { data: cards = [] } = useQuery<FlashcardRow[]>({
    queryKey: ['flashcards-due'],
    queryFn: async () => {
      try {
        return await api<FlashcardRow[]>('/v1/flashcards/due');
      } catch {
        return [];
      }
    },
    staleTime: 60_000,
  });

  // No real deck endpoint yet — derive a single "Due now" pseudo-deck from
  // /v1/flashcards/due so the cards tab shows real data when present.
  const decks = cards.length > 0 ? [{ t: 'Due now', count: cards.length, due: cards.length, m: 0 }] : [];

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
              Notes <b className="font-bold tabular-nums">{notes.length}</b>
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
              Flashcards <b className="font-bold">{cards.length}</b>
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
        <>
          {notes.length === 0 && !notesLoading && (
            <div className="mt-10 rounded-2xl border border-dashed border-border bg-white px-6 py-14 text-center">
              <div className="text-base font-semibold text-ink">No notes yet</div>
              <div className="mt-1 text-sm text-ink-3">
                When Aria saves a key idea or you write your own, it’ll show up here.
              </div>
            </div>
          )}
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {notes.map((n) => (
              <NoteCard
                key={n.id}
                color={(n.color as NoteColor) ?? ''}
                tag={tagFor(n)}
                title={n.title ?? 'Untitled'}
                body={n.body ?? ''}
                date={fmtDate(n.updated_at || n.created_at)}
              />
            ))}
          </div>
        </>
      )}

      {tab === 'cards' && (
        <>
          {decks.length === 0 && (
            <div className="mt-10 rounded-2xl border border-dashed border-border bg-white px-6 py-14 text-center">
              <div className="text-base font-semibold text-ink">No flashcards due</div>
              <div className="mt-1 text-sm text-ink-3">
                Cards appear here as Aria builds them from your lesson Q&amp;A.
              </div>
            </div>
          )}
          <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2">
            {decks.map((d, i) => (
              <DeckRow
                key={i}
                title={d.t}
                count={d.count}
                due={d.due}
                mastery={d.m}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
