'use client';

import { useState } from 'react';

import { cn } from '@/lib/utils';

export interface Reaction {
  id: string;
  icon: string;
  label: string;
  /** What Aria says back when the student fires this reaction. */
  msg: string;
}

export const REACTIONS: Reaction[] = [
  {
    id: 'slower',
    icon: '🐢',
    label: 'Slow down',
    msg: 'Got it — let me slow down a bit and re-explain that.',
  },
  {
    id: 'confused',
    icon: '😕',
    label: "I'm lost",
    msg: 'I hear you. Let me back up and try a different angle.',
  },
  {
    id: 'gotit',
    icon: '💡',
    label: 'Got it!',
    msg: "Nice — feels good when it clicks. Let's keep going.",
  },
  {
    id: 'mindblown',
    icon: '🤯',
    label: 'Whoa',
    msg: "Right? Physics is wild. Wait till you see what's next.",
  },
];

interface ReactionsClusterProps {
  onReact: (r: Reaction) => void;
  /**
   * Optional controlled open state. When provided, the cluster's
   * visibility is driven by the parent (e.g. the bottom-dock "React"
   * button); omit both to keep the original self-managed behaviour.
   */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

interface Pop {
  id: number;
  icon: string;
  x: number;
}

let popSeq = 0;

/**
 * Vertical cluster of reaction buttons on the left edge.
 * Clicking fires the emoji upward via `reaction-fly` CSS animation.
 */
export function ReactionsCluster({
  onReact,
  open: openProp,
  onOpenChange,
}: ReactionsClusterProps) {
  const [openState, setOpenState] = useState(true);
  const open = openProp ?? openState;
  const setOpen = (next: boolean | ((o: boolean) => boolean)) => {
    const value = typeof next === 'function' ? next(open) : next;
    if (openProp === undefined) setOpenState(value);
    onOpenChange?.(value);
  };
  const [pops, setPops] = useState<Pop[]>([]);

  const fire = (r: Reaction) => {
    const id = ++popSeq;
    const pop: Pop = { id, icon: r.icon, x: 60 + Math.random() * 20 };
    setPops((p) => [...p, pop]);
    setTimeout(() => setPops((p) => p.filter((x) => x.id !== id)), 1800);
    onReact(r);
  };

  return (
    <div className={cn('cr-reactions', !open && 'collapsed')}>
      <div className="cr-reactions-pops">
        {pops.map((p) => (
          <span key={p.id} className="cr-reaction-pop" style={{ left: `${p.x}px` }}>
            {p.icon}
          </span>
        ))}
      </div>
      <button
        type="button"
        className="cr-reactions-toggle"
        onClick={() => setOpen((o) => !o)}
        title="Reactions"
        aria-label={open ? 'Hide reactions' : 'Show reactions'}
      >
        {open ? '×' : '🤔'}
      </button>
      {open &&
        REACTIONS.map((r) => (
          <button
            key={r.id}
            type="button"
            className={`cr-reaction-btn r-${r.id}`}
            onClick={() => fire(r)}
            title={r.label}
          >
            <span className="ic" aria-hidden>
              {r.icon}
            </span>
            <span className="lbl">{r.label}</span>
          </button>
        ))}
    </div>
  );
}
