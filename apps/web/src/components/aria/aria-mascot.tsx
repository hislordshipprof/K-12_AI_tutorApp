import type { CSSProperties } from 'react';

import { cn } from '@/lib/utils';

export interface AriaMascotProps {
  /** Diameter in pixels. Defaults to 80. */
  size?: number;
  /** Animates the mouth to suggest speech. */
  speaking?: boolean;
  /** Adds the gentle vertical bob animation. */
  pulse?: boolean;
  /** Renders the graduation cap on top. */
  withHat?: boolean;
  /** Renders the breathing indigo ring around the mascot. */
  withRing?: boolean;
  className?: string;
}

/**
 * Aria — the indigo orb mascot that anchors every screen.
 *
 * Visuals (radial gradients, eye/cheek/smile/hat geometry) are ported
 * verbatim from `styles.css`. The CSS lives in `globals.css` under
 * `@layer components` to keep gradient definitions cohesive.
 */
export function AriaMascot({
  size = 80,
  speaking = false,
  pulse = false,
  withHat = true,
  withRing = false,
  className,
}: AriaMascotProps) {
  return (
    <div
      className={cn('relative inline-block', className)}
      style={{ width: size, height: size }}
    >
      {withRing && <span className="aria-ring" aria-hidden="true" />}
      <div
        className={cn('aria-mascot', pulse && 'pulse', speaking && 'speaking')}
        style={{ ['--sz' as string]: `${size}px` } as CSSProperties}
        role="img"
        aria-label="Aria — your AI tutor"
      >
        {withHat && <span className="hat" />}
        <span className="eye l" />
        <span className="eye r" />
        <span className="cheek l" />
        <span className="cheek r" />
        <span className="smile" />
      </div>
    </div>
  );
}
