'use client';

import { useEffect } from 'react';

import { Icon } from '@/components/aria/icon';
import { Waveform } from '@/components/classroom/waveform';
import { useListen } from '@/hooks/use-listen';
import { cn } from '@/lib/utils';

interface VoiceModeProps {
  active: boolean;
  onCancel: () => void;
  onSubmit: (text: string) => void;
}

/**
 * Fullscreen voice overlay — mic orb, live transcript, cancel/send.
 *
 * Auto-starts listening when `active` becomes true. On send, hands the
 * trimmed transcript to the parent so it can be POSTed to Q&A.
 */
export function VoiceMode({ active, onCancel, onSubmit }: VoiceModeProps) {
  const { listening, transcript, start, stop, setTranscript } = useListen();

  // Auto-start when opened, stop when closed.
  useEffect(() => {
    if (active) {
      start();
    } else {
      stop();
      setTranscript('');
    }
    return () => stop();
  }, [active, start, stop, setTranscript]);

  const finish = () => {
    stop();
    const text = transcript.trim();
    if (text.length > 0) {
      setTimeout(() => onSubmit(text), 200);
    } else {
      onCancel();
    }
  };

  return (
    <div className={cn('vm-ov', active && 'active')}>
      <div className="vm-dim" onClick={onCancel} role="presentation" />
      <div className="vm-stage">
        <div className="vm-hint">{listening ? "I'm listening…" : "Tap when you're done"}</div>

        <div className={cn('vm-mic-orb', listening && 'live')}>
          <Waveform active={listening} />
          <div className="vm-mic-core">
            <Icon name="mic" size={32} />
          </div>
          <span className="vm-ring r1" />
          <span className="vm-ring r2" />
          <span className="vm-ring r3" />
        </div>

        <div className="vm-transcript">
          {transcript || (
            <span className="vm-placeholder">Say anything — I&apos;ll draw the answer.</span>
          )}
          {listening && transcript && <span className="vm-cursor" />}
        </div>

        <div className="vm-actions">
          <button type="button" className="vm-btn vm-cancel" onClick={onCancel}>
            <Icon name="close" size={16} /> Cancel
          </button>
          <button
            type="button"
            className="vm-btn vm-send"
            onClick={finish}
            disabled={!transcript.trim()}
          >
            <Icon name="send" size={16} /> Ask Aria
          </button>
        </div>
      </div>
    </div>
  );
}
