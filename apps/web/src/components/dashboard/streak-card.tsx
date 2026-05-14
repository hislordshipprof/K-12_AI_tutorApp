import { cn } from '@/lib/utils';

export interface StreakCardProps {
  days: number;
  /** Day-of-week labels. Defaults to Mon–Sun. */
  labels?: readonly string[];
}

const DEFAULT_LABELS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'] as const;

/**
 * Day-streak summary card — big number + week-pill row.
 *
 * Ported from `.streak-card` in the prototype.
 */
export function StreakCard({ days, labels = DEFAULT_LABELS }: StreakCardProps) {
  return (
    <div className="relative overflow-hidden rounded-[18px] bg-gradient-to-br from-[#FFF1C9] to-[#FFD879] p-5 text-[#5C3A00]">
      <div
        className="pointer-events-none absolute -right-[20%] -top-[30%] h-[120%] w-[120%]"
        style={{
          background:
            'radial-gradient(circle, rgba(255,255,255,.3), transparent 60%)',
        }}
      />
      <div className="relative font-display text-[64px] font-bold leading-none tracking-[-0.04em]">
        {days}
      </div>
      <div className="relative mt-1.5 text-sm font-bold">day streak 🔥</div>
      <div className="relative mt-1 text-xs leading-[1.4] opacity-70">
        Study one lesson tomorrow to keep it going.
      </div>
      <div className="relative mt-4 flex gap-1.5">
        {labels.map((d, i) => (
          <div
            key={i}
            className={cn(
              'grid h-8 flex-1 place-items-center rounded-lg text-[11px] font-bold text-[#5C3A00]',
              i < days
                ? 'bg-white shadow-[0_4px_10px_rgba(0,0,0,0.08)]'
                : 'bg-white/40',
            )}
          >
            {d}
          </div>
        ))}
      </div>
    </div>
  );
}
