'use client';

import { useEffect, useRef, useState } from 'react';

import { Icon } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

interface ReplyBarProps {
  visible: boolean;
  placeholder?: string;
  onSubmit: (text: string) => void;
  onVoice: () => void;
}

/**
 * Bottom input bar for the student to type or speak back at Aria
 * while sketching. Empty submissions are ignored.
 */
export function ReplyBar({
  visible,
  placeholder = 'Type your answer to Aria…',
  onSubmit,
  onVoice,
}: ReplyBarProps) {
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Clear when hidden.
  useEffect(() => {
    if (!visible) setText('');
  }, [visible]);

  const submit = () => {
    const t = text.trim();
    if (!t) return;
    onSubmit(t);
    setText('');
  };

  return (
    <div className={cn('reply-bar', visible && 'open')}>
      <div className="rb-label">↳ Reply to Aria</div>
      <input
        ref={inputRef}
        type="text"
        className="rb-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            submit();
          }
        }}
        placeholder={placeholder}
      />
      <button type="button" className="rb-mic" onClick={onVoice} title="Speak your answer">
        <Icon name="mic" size={16} />
      </button>
      <button
        type="button"
        className="rb-send"
        onClick={submit}
        disabled={!text.trim()}
        title="Send"
      >
        <Icon name="send" size={14} />
      </button>
    </div>
  );
}
