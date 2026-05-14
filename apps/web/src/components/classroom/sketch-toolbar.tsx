'use client';

import { Icon } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

interface ChalkColor {
  v: string;
  name: string;
}

const COLORS: ChalkColor[] = [
  { v: 'rgba(255,255,255,.85)', name: 'white' },
  { v: '#F5E067', name: 'yellow' },
  { v: '#F09AAF', name: 'pink' },
  { v: '#7DD4A8', name: 'green' },
];

interface SketchToolbarProps {
  visible: boolean;
  color: string;
  setColor: (c: string) => void;
  eraser: boolean;
  setEraser: (b: boolean) => void;
  onUndo: () => void;
  onClear: () => void;
  onClose: () => void;
  onHint: () => void;
}

/**
 * Floating toolbar for the sketch overlay: chalk colors, eraser toggle,
 * undo, clear, hint request, and close.
 */
export function SketchToolbar({
  visible,
  color,
  setColor,
  eraser,
  setEraser,
  onUndo,
  onClear,
  onClose,
  onHint,
}: SketchToolbarProps) {
  return (
    <div className={cn('sketch-toolbar', visible && 'open')}>
      <div className="st-section">
        <div className="st-label">Chalk</div>
        <div className="st-colors">
          {COLORS.map((c) => (
            <button
              key={c.v}
              type="button"
              className={cn('st-color', color === c.v && !eraser && 'active')}
              style={{ background: c.v }}
              onClick={() => {
                setColor(c.v);
                setEraser(false);
              }}
              title={c.name}
              aria-label={`${c.name} chalk`}
            />
          ))}
        </div>
      </div>
      <div className="st-section">
        <div className="st-label">Tools</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            className={cn('st-btn', eraser && 'active')}
            onClick={() => setEraser(!eraser)}
            title="Eraser"
          >
            <span aria-hidden>🧽</span>
            <span className="sr-only">Eraser</span>
          </button>
          <button type="button" className="st-btn" onClick={onUndo} title="Undo">
            <Icon name="prev" size={13} />
          </button>
          <button type="button" className="st-btn" onClick={onClear} title="Clear all">
            Clear
          </button>
        </div>
      </div>
      <div className="st-section">
        <button type="button" className="st-hint" onClick={onHint}>
          <Icon name="sparkle" size={13} /> Ask for a hint
        </button>
      </div>
      <button type="button" className="st-close" onClick={onClose} title="Exit sketch">
        <Icon name="close" size={14} />
      </button>
    </div>
  );
}
