/**
 * Static peer-presence badge — "3 here now" with three avatar bubbles.
 *
 * Real presence will wire to Supabase Realtime in a later iteration;
 * for now the prototype's hard-coded peers ship the same vibe.
 */
const PEERS = [
  { i: 'SR', c: 'linear-gradient(135deg,#FF7A59,#FFC857)' },
  { i: 'KA', c: 'linear-gradient(135deg,#5B5BE5,#A78BFA)' },
  { i: 'MJ', c: 'linear-gradient(135deg,#34C97A,#5FB7F4)' },
];

export function PeerPresence() {
  return (
    <div className="peer-presence" title="3 students studying this lesson right now">
      <div className="peer-avs">
        {PEERS.map((p, i) => (
          <span key={i} className="peer-av" style={{ background: p.c }}>
            {p.i}
          </span>
        ))}
      </div>
      <div className="peer-text">
        <b>3</b> here now
      </div>
    </div>
  );
}
