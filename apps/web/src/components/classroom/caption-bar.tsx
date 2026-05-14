'use client';

import type { ReactNode } from 'react';

import { AriaMascot } from '@/components/aria/aria-mascot';
import { Icon } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

interface CaptionBarProps {
  /** Speaker label shown above the caption (e.g. "speaking", "paused"). */
  who: string;
  /** Whether to render the green speaking-bars indicator. */
  showBars: boolean;
  /** Whether to animate Aria's mouth. */
  speaking: boolean;
  /** Adds the yellow "reacting to you" border treatment. */
  reacting?: boolean;
  /** Caption body — JSX so we can syntax-highlight key terms. */
  text: ReactNode;
  onAsk: () => void;
  onVoice: () => void;
}

/**
 * Bottom caption bar: Aria avatar + speaker label + caption text,
 * plus the "Voice" and "Raise hand" CTAs to the right.
 */
export function CaptionBar({
  who,
  showBars,
  speaking,
  reacting = false,
  text,
  onAsk,
  onVoice,
}: CaptionBarProps) {
  return (
    <div className="cr-bottom">
      <div
        style={{
          display: 'flex',
          gap: 12,
          alignItems: 'stretch',
          maxWidth: 1100,
          margin: '0 auto',
          justifyContent: 'center',
        }}
      >
        <div className={cn('cr-cap', reacting && 'reacting')}>
          <div className="cr-cap-av">
            <AriaMascot size={44} speaking={speaking} />
          </div>
          <div className="cr-cap-body">
            <div className="cr-cap-who">
              Prof. Aria · {who}
              {showBars && (
                <span className="sw">
                  <span className="sw-b" />
                  <span className="sw-b" />
                  <span className="sw-b" />
                  <span className="sw-b" />
                </span>
              )}
            </div>
            <div className="cr-cap-txt">{text}</div>
          </div>
        </div>
        <button
          type="button"
          className="cr-mic"
          onClick={onVoice}
          title="Hold to talk to Aria"
        >
          <div className="ic">
            <Icon name="mic" size={16} />
          </div>
          <span className="lbl">Voice</span>
        </button>
        <button type="button" className="cr-ask" onClick={onAsk}>
          <div className="ic">
            <Icon name="hand" size={14} />
          </div>
          Raise hand
          <span className="kbd">SPACE</span>
        </button>
      </div>
    </div>
  );
}
