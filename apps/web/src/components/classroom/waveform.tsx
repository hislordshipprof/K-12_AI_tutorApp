import { cn } from '@/lib/utils';

interface WaveformProps {
  active: boolean;
  bars?: number;
}

/**
 * Animated bar group that fakes a live audio waveform.
 * Each bar gets a deterministic delay/duration so the pattern feels
 * organic without needing real audio analysis.
 */
export function Waveform({ active, bars = 22 }: WaveformProps) {
  return (
    <div className={cn('wf', active && 'live')}>
      {Array.from({ length: bars }).map((_, i) => (
        <span
          key={i}
          style={{
            animationDelay: `${(i * 73) % 700}ms`,
            animationDuration: `${600 + ((i * 47) % 500)}ms`,
          }}
        />
      ))}
    </div>
  );
}
