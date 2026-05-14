'use client';

import { cn } from '@/lib/utils';

interface VoiceBarProps {
  muted: boolean;
  onMute: () => void;
  speaking: boolean;
}

/**
 * Tiny mute toggle + speaking-indicator pill that lives in the top
 * control cluster. Mirrors the prototype's `VoiceBar`.
 */
export function VoiceBar({ muted, onMute, speaking }: VoiceBarProps) {
  return (
    <div className={cn('cr-voicebar', speaking && 'live', muted && 'muted')}>
      <button
        type="button"
        className="cr-voicebar-toggle"
        onClick={onMute}
        title={muted ? 'Unmute Aria' : 'Mute Aria'}
        aria-pressed={!muted}
      >
        {muted ? '🔇' : '🔊'}
      </button>
      {speaking && !muted && (
        <span className="cr-voicebar-bars">
          <span />
          <span />
          <span />
          <span />
        </span>
      )}
    </div>
  );
}
