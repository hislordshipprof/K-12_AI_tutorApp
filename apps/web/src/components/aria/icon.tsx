import type { SVGProps } from 'react';

import { cn } from '@/lib/utils';

/**
 * Hand-tuned SVG path data ported verbatim from the prototype's
 * `components.jsx`. All icons are drawn on a 24x24 viewBox with
 * `currentColor` strokes.
 */
export const ICON_PATHS = {
  home: 'M3 12 L12 4 L21 12 M5 11 V20 H10 V14 H14 V20 H19 V11',
  planner: 'M3 6 H21 M3 12 H21 M3 18 H21 M8 4 V8 M16 4 V8',
  notes: 'M5 4 H14 L19 9 V20 H5 Z M14 4 V9 H19',
  history: 'M12 8 V12 L15 14 M3 12 A9 9 0 1 0 6 5.3 M3 5 V10 H8',
  course:
    'M4 5 V19 A2 2 0 0 0 6 21 H20 V7 H6 A2 2 0 0 1 4 5 A2 2 0 0 1 6 3 H20',
  chat: 'M21 12 A9 8 0 1 1 12 4 A9 8 0 0 1 21 12 L21 19 L17 17 A9 8 0 0 1 12 20',
  settings:
    'M12 9 A3 3 0 1 0 12 15 A3 3 0 1 0 12 9 Z M19 12 L21 13 V14 L19 15 L18 17 L19 19 L18 20 L16 19 L14 20 L13 22 H11 L10 20 L8 19 L6 20 L5 19 L6 17 L5 15 L3 14 V13 L5 12 L6 10 L5 8 L6 7 L8 8 L10 7 L11 5 H13 L14 7 L16 8 L18 7 L19 8 L18 10 Z',
  play: 'M7 4 V20 L20 12 Z',
  pause: 'M7 4 H10 V20 H7 Z M14 4 H17 V20 H14 Z',
  prev: 'M14 6 L8 12 L14 18',
  next: 'M10 6 L16 12 L10 18',
  close: 'M6 6 L18 18 M18 6 L6 18',
  hand: 'M9 11 V5 A1.5 1.5 0 0 1 12 5 V11 M12 11 V4 A1.5 1.5 0 0 1 15 4 V11 M15 11 V5 A1.5 1.5 0 0 1 18 5 V13 C18 17 16 21 12 21 C8 21 6 18 6 15 V11 A1.5 1.5 0 0 1 9 11',
  send: 'M3 20 L21 12 L3 4 L5 12 L3 20 M5 12 H14',
  mic: 'M12 4 A3 3 0 0 0 9 7 V12 A3 3 0 0 0 15 12 V7 A3 3 0 0 0 12 4 Z M5 11 A7 7 0 0 0 19 11 M12 18 V22 M9 22 H15',
  arrow: 'M5 12 H19 M13 6 L19 12 L13 18',
  chev: 'M9 6 L15 12 L9 18',
  check: 'M5 12 L10 17 L19 7',
  sparkle: 'M12 3 L13.5 9 L20 10.5 L13.5 12 L12 18 L10.5 12 L4 10.5 L10.5 9 Z',
  book: 'M5 5 V20 A2 2 0 0 0 7 22 H19 V4 H7 A2 2 0 0 0 5 6 Z M9 8 H15 M9 12 H15',
  voice: 'M3 12 H5 M19 12 H21 M7 9 V15 M11 5 V19 M15 7 V17',
  layout: 'M4 4 H20 V20 H4 Z M14 4 V20 M4 12 H14',
  bell: 'M6 16 V11 A6 6 0 0 1 18 11 V16 L20 18 H4 Z M10 21 A2 2 0 0 0 14 21',
  search: 'M11 4 A7 7 0 1 0 11 18 A7 7 0 0 0 11 4 Z M16 16 L21 21',
  plus: 'M12 5 V19 M5 12 H19',
  download: 'M12 4 V16 M7 11 L12 16 L17 11 M4 20 H20',
  fire: 'M12 22 C7 22 4 18 4 14 C4 11 6 9 8 7 C9 9 11 10 11 8 C11 5 13 4 12 2 C16 4 20 8 20 14 C20 18 17 22 12 22 Z',
  users:
    'M16 21 V19 A4 4 0 0 0 12 15 H6 A4 4 0 0 0 2 19 V21 M13 7 A4 4 0 0 1 5 7 A4 4 0 0 1 13 7 M22 21 V19 A4 4 0 0 0 19 15.13 M16 3.13 A4 4 0 0 1 16 10.87',
} as const;

export type IconName = keyof typeof ICON_PATHS;

export interface IconProps
  extends Omit<SVGProps<SVGSVGElement>, 'name' | 'stroke'> {
  name: IconName;
  /** Pixel size for both width and height. Defaults to 20. */
  size?: number;
  /** Stroke width in pixels. Defaults to 2. */
  stroke?: number;
}

/**
 * Lightweight line-icon component (24x24 viewBox, currentColor stroke).
 *
 * Returns `null` for unknown icon names so consumers can safely fall back
 * to a Lucide icon or text label without throwing.
 */
export function Icon({
  name,
  size = 20,
  stroke = 2,
  className,
  ...rest
}: IconProps) {
  const d = ICON_PATHS[name];
  if (!d) return null;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn('shrink-0', className)}
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path d={d} />
    </svg>
  );
}
