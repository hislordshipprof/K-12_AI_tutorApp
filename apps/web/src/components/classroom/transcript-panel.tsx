'use client';

import { useEffect, useRef } from 'react';

import { TimedReveal } from '@/components/aria/timed-reveal';

/**
 * One conversation turn in the live transcript. Aria turns are lesson
 * narration (or her reactions); student turns are captured replies / voice.
 * The `current` turn streams in word-by-word as Aria narrates.
 */
export interface TranscriptTurn {
  /** Stable key — usually the lesson step index for Aria narration turns. */
  id: string;
  who: 'aria' | 'student';
  /** Plain text for student turns / settled Aria turns. */
  text?: string;
  /** Mixed HTML+LaTeX — used for the streaming current Aria turn. */
  html?: string;
  /** True for the single turn that is being spoken / streamed right now. */
  current?: boolean;
}

interface TranscriptPanelProps {
  /** Ordered conversation turns, oldest first. */
  turns: TranscriptTurn[];
  /** 0→1 reveal progress for the current streaming Aria turn. */
  progress: number;
  /** True while Aria is narrating — drives the footer + equalizer. */
  ariaSpeaking: boolean;
  /** True while the classroom is in voice mode (listening for the student). */
  listening: boolean;
  /** Collapse the panel down to nothing (controlled by the top-bar button). */
  collapsed: boolean;
  /** Collapse button handler. */
  onCollapse: () => void;
}

function Equalizer({ className = '' }: { className?: string }) {
  return (
    <span className={`flex items-end gap-0.5 h-3.5 ${className}`}>
      <span className="cr-eqbar" />
      <span className="cr-eqbar" style={{ animationDelay: '.15s' }} />
      <span className="cr-eqbar" style={{ animationDelay: '.3s' }} />
      <span className="cr-eqbar" style={{ animationDelay: '.1s' }} />
    </span>
  );
}

/**
 * Right-side live transcript panel — a scrolling conversation log between
 * Prof. Aria and the student. Aria's current turn streams in via
 * `TimedReveal`, synced to the lesson TTS clock through `progress`.
 */
export function TranscriptPanel({
  turns,
  progress,
  ariaSpeaking,
  listening,
  collapsed,
  onCollapse,
}: TranscriptPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the newest turn in view as the conversation grows / streams.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns.length, progress]);

  if (collapsed) return null;

  return (
    <aside className="w-[340px] bg-[#1c2b3c]/45 backdrop-blur-md rounded-2xl border border-white/10 flex flex-col overflow-hidden shadow-xl shrink-0">
      {/* header */}
      <div className="px-4 py-3 border-b border-white/5 bg-[#273647]/40 flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center relative shrink-0">
          <span className="material-symbols-outlined fill text-white text-[20px]">school</span>
          <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-green-500 border-2 border-[#273647] rounded-full" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-[11px] font-bold tracking-[0.1em] text-[#ffb95f]">PROF. ARIA</h2>
          <p className="text-[11px] text-[#c6c6cd] flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500" /> Live transcript
          </p>
        </div>
        <button
          type="button"
          onClick={onCollapse}
          className="w-8 h-8 rounded-full flex items-center justify-center text-[#c6c6cd] hover:bg-white/5"
          title="Collapse transcript"
        >
          <span className="material-symbols-outlined text-[18px]">right_panel_open</span>
        </button>
      </div>

      {/* messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-5 cr-scroll min-h-0">
        {turns.length === 0 && (
          <p className="text-[12px] text-[#c6c6cd]/60 text-center py-6">
            The conversation will appear here as Aria teaches.
          </p>
        )}
        {turns.map((turn) => {
          if (turn.who === 'student') {
            return (
              <div key={turn.id} className="opacity-80">
                <div className="flex items-center justify-end gap-1.5 mb-1.5">
                  <span className="text-[10px] text-[#7bd0ff] font-semibold tracking-wide">YOU</span>
                </div>
                <div className="bg-[#00a6e0]/12 p-3 rounded-xl rounded-tr-sm border border-[#7bd0ff]/20">
                  <p className="text-[14px] leading-[22px]">{turn.text}</p>
                </div>
              </div>
            );
          }
          if (turn.current) {
            return (
              <div key={turn.id}>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <span className="text-[10px] text-[#ffb95f] font-bold tracking-wide">ARIA · NOW</span>
                  {ariaSpeaking && (
                    <span className="flex items-end gap-0.5 h-2.5 text-[#ffb95f]">
                      <span className="cr-eqbar" />
                      <span className="cr-eqbar" style={{ animationDelay: '.2s' }} />
                      <span className="cr-eqbar" style={{ animationDelay: '.4s' }} />
                    </span>
                  )}
                </div>
                <div className="bg-[#ffb95f]/10 p-3 rounded-xl rounded-tl-sm border-l-[3px] border-[#ffb95f]">
                  <p className="text-[14px] leading-[22px] font-medium text-[#d4e4fa]">
                    {turn.html ? (
                      <TimedReveal html={turn.html} progress={progress} />
                    ) : (
                      turn.text
                    )}
                    {progress < 1 && (
                      <span className="cr-caret text-[#ffb95f] font-bold">▍</span>
                    )}
                  </p>
                </div>
              </div>
            );
          }
          // settled (earlier) Aria turn
          return (
            <div key={turn.id} className="opacity-60">
              <span className="text-[10px] text-[#c6c6cd] font-semibold tracking-wide">ARIA</span>
              <div className="mt-1.5 bg-[#0d1c2d] p-3 rounded-xl rounded-tl-sm border border-white/5">
                <p className="text-[14px] leading-[22px] text-[#d4e4fa]">{turn.text}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* live status footer */}
      <div className="px-4 py-3 border-t border-white/5 bg-[#273647]/30 flex items-center gap-2 text-[#ffb95f]">
        {listening ? (
          <>
            <span className="material-symbols-outlined text-[18px]">hearing</span>
            <span className="text-[11px] font-bold tracking-[0.08em]">ARIA IS LISTENING</span>
          </>
        ) : ariaSpeaking ? (
          <>
            <span className="material-symbols-outlined text-[18px]">graphic_eq</span>
            <span className="text-[11px] font-bold tracking-[0.08em]">ARIA SPEAKING</span>
            <Equalizer className="ml-auto" />
          </>
        ) : (
          <>
            <span className="material-symbols-outlined text-[18px]">pause_circle</span>
            <span className="text-[11px] font-bold tracking-[0.08em]">PAUSED</span>
          </>
        )}
      </div>
    </aside>
  );
}
