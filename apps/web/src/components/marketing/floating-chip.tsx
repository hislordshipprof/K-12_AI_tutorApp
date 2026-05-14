import type { ReactNode } from 'react';

import { Icon, type IconName } from '@/components/aria/icon';
import { cn } from '@/lib/utils';

export interface FloatingChipProps {
  icon: IconName;
  label: ReactNode;
  /** Tailwind text-color class, e.g. `text-mint`. */
  toneClassName: string;
  /** Tailwind bg-color class for the icon square, e.g. `bg-mint`. */
  iconBgClassName: string;
  /** Tailwind absolute-position utilities, e.g. `top-[30px] -left-10`. */
  positionClassName: string;
  /** Animation delay in seconds (chips stagger their float bob). */
  delaySeconds?: number;
}

/**
 * White rounded chip with coloured icon square that floats around the
 * hero board on the landing page. Mirrors the prototype's `.l-float`.
 */
export function FloatingChip({
  icon,
  label,
  toneClassName,
  iconBgClassName,
  positionClassName,
  delaySeconds = 0,
}: FloatingChipProps) {
  return (
    <div
      className={cn(
        'absolute hidden animate-float items-center gap-2.5 rounded-[14px] bg-white px-3.5 py-2.5 text-[13px] font-semibold shadow-lg lg:flex',
        toneClassName,
        positionClassName,
      )}
      style={{ animationDelay: `${delaySeconds}s` }}
    >
      <div
        className={cn(
          'grid h-6 w-6 place-items-center rounded-[7px] text-white',
          iconBgClassName,
        )}
      >
        <Icon name={icon} size={14} />
      </div>
      {label}
    </div>
  );
}
