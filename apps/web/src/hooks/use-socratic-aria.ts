'use client';

import { useEffect, useState } from 'react';

export type RecognizedShape =
  | 'wave'
  | 'horizontal-line'
  | 'vertical-line'
  | 'diagonal-line'
  | 'curve'
  | 'circle'
  | 'writing'
  | 'writing-cluster'
  | 'sketch'
  | null;

export type SocraticTone = 'prompt' | 'soft' | 'hint';

export interface SocraticMessage {
  who: string;
  text: string;
  tone: SocraticTone;
}

interface UseSocraticAriaArgs {
  active: boolean;
  strokeCount: number;
  /** Timestamp of last stroke (ms). 0 if none. */
  lastStrokeAt: number;
  /** Monotonically increasing counter of hint requests. */
  hintsRequested: number;
  recognizedShape: RecognizedShape;
  /** Optional student-typed reply to react to. */
  studentReply: string | null;
}

/**
 * Drive the Socratic-Aria prompt while the student is sketching.
 *
 * Layered effects: open prompt → shape-specific reaction → fallback by
 * stroke count → student reply → progressive hints → idle nudge. The
 * latest `setMsg` call wins, so the order of `useEffect`s matters.
 */
export function useSocraticAria({
  active,
  strokeCount,
  lastStrokeAt,
  hintsRequested,
  recognizedShape,
  studentReply,
}: UseSocraticAriaArgs): SocraticMessage | null {
  const [msg, setMsg] = useState<SocraticMessage | null>(null);

  // Open prompt.
  useEffect(() => {
    if (!active) {
      setMsg(null);
      return;
    }
    setMsg({
      who: 'Aria · watching you work',
      text: "Go ahead — I'll watch. What are you trying to figure out?",
      tone: 'prompt',
    });
  }, [active]);

  // React to recognized shape.
  useEffect(() => {
    if (!active || !recognizedShape) return;
    const map: Record<Exclude<RecognizedShape, null>, SocraticMessage> = {
      wave: {
        who: 'Aria · I see the wave',
        text: 'Nice — that looks like the wave we just drew. Where would you mark the amplitude on it?',
        tone: 'prompt',
      },
      'horizontal-line': {
        who: 'Aria',
        text: "Good — looks like the equilibrium line. That's where the wave oscillates around. What's next?",
        tone: 'prompt',
      },
      'vertical-line': {
        who: 'Aria',
        text: 'An up-down line — is that an amplitude marker? Tell me what it represents.',
        tone: 'prompt',
      },
      'diagonal-line': {
        who: 'Aria',
        text: 'I see a line. Is that part of an axis, or are you connecting two points?',
        tone: 'prompt',
      },
      curve: {
        who: 'Aria · I see a bump',
        text: 'A single hump — like a crest? Or maybe half a wavelength. Which one are you thinking?',
        tone: 'prompt',
      },
      circle: {
        who: 'Aria',
        text: 'Circles on the board often mark something specific — a crest, a node? Tell me what you mean.',
        tone: 'prompt',
      },
      'writing-cluster': {
        who: 'Aria · reading your work',
        text: "Looks like you're writing something out — an equation? Walk me through what you have so far.",
        tone: 'prompt',
      },
      writing: {
        who: 'Aria',
        text: "I see a mark — labeling something? Keep going, I'm watching.",
        tone: 'soft',
      },
      sketch: {
        who: 'Aria',
        text: "Hmm — interesting shape. What's it supposed to be?",
        tone: 'soft',
      },
    };
    const next = map[recognizedShape];
    if (next) setMsg(next);
  }, [recognizedShape, active]);

  // Fallback by stroke count when no shape was recognized.
  useEffect(() => {
    if (!active || recognizedShape) return;
    if (strokeCount === 1) {
      setMsg({
        who: 'Aria · listening',
        text: "Nice — you're starting. Walk me through it. What's that piece supposed to represent?",
        tone: 'prompt',
      });
    }
  }, [strokeCount, active, recognizedShape]);

  // React to student replies (text or transcribed voice).
  useEffect(() => {
    if (!active || !studentReply) return;
    const r = studentReply.toLowerCase();
    let resp: SocraticMessage;
    if (/v\s*=\s*f.*λ|v.*=.*f.*lambda|wave.*speed/.test(r)) {
      resp = {
        who: 'Aria · spot on',
        text: 'Yes — v = f · λ. Now, if you know two of those three, you can find the third. Which two are you given?',
        tone: 'prompt',
      };
    } else if (/amplitude|tall|height|energy/.test(r)) {
      resp = {
        who: 'Aria',
        text: 'Good — amplitude is the height from rest. What does bigger amplitude mean physically?',
        tone: 'prompt',
      };
    } else if (/wavelength|λ|lambda|cycle|peak to peak/.test(r)) {
      resp = {
        who: 'Aria',
        text: 'Right — wavelength is the distance for one full cycle. How is that different from period?',
        tone: 'prompt',
      };
    } else if (/frequency|hz|cycles per/.test(r)) {
      resp = {
        who: 'Aria',
        text: "Yes. Frequency is how often. What's its inverse called? (Hint: it starts with 'p'.)",
        tone: 'prompt',
      };
    } else if (/don'?t know|idk|stuck|lost|no idea/.test(r)) {
      resp = {
        who: 'Aria · here for you',
        text: "That's totally fine. Let's back up. What's the first thing you're certain about on this problem?",
        tone: 'soft',
      };
    } else if (/yes|yeah|got it|i think/.test(r)) {
      resp = {
        who: 'Aria',
        text: "Cool. Show me on the board — sketch what you mean. I'll follow along.",
        tone: 'prompt',
      };
    } else if (r.length < 5) {
      resp = {
        who: 'Aria',
        text: "Tell me a little more — what's going through your head?",
        tone: 'soft',
      };
    } else {
      resp = {
        who: 'Aria · listening',
        text: `"${studentReply}" — OK, keep going. What makes you think that?`,
        tone: 'prompt',
      };
    }
    setMsg(resp);
  }, [studentReply, active]);

  // Progressive hints (clamped to 3 levels).
  useEffect(() => {
    if (!active || hintsRequested === 0) return;
    const hints: SocraticMessage[] = [
      {
        who: 'Aria · hint 1 of 3',
        text: 'Start with what you know. We have wave speed (v), frequency (f), and wavelength (λ). Which two are given to you?',
        tone: 'hint',
      },
      {
        who: 'Aria · hint 2 of 3',
        text: 'Right. Now — what equation connects those three? Try writing it before I show you.',
        tone: 'hint',
      },
      {
        who: 'Aria · hint 3 of 3',
        text: "It's v = f · λ. Plug in the values yourself. Write each step — don't skip the arithmetic.",
        tone: 'hint',
      },
    ];
    const idx = Math.min(hintsRequested - 1, hints.length - 1);
    const h = hints[idx];
    if (h) setMsg(h);
  }, [hintsRequested, active]);

  // Idle prompt — 8s after the most recent stroke.
  useEffect(() => {
    if (!active || !lastStrokeAt) return;
    const t = setTimeout(() => {
      setMsg({
        who: 'Aria · waiting',
        text: "Still thinking? Good — that means you're not just copying. Tap *Ask for a hint* or type me a question.",
        tone: 'soft',
      });
    }, 8000);
    return () => clearTimeout(t);
  }, [lastStrokeAt, active]);

  return msg;
}
