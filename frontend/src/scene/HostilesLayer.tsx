import { Html } from '@react-three/drei';
import { useGdsStore } from '../store';
import { groundY } from './UnitsLayer';
import type { ResolvedContact } from '../types';

function tagFor(c: ResolvedContact): string | null {
  // Every contact's shot is simulated (no real audio anywhere in this demo);
  // the tag communicates whether the LOCALISATION was actually computed by
  // the real backend or is a client fallback — true for presets and manual
  // clicks alike now that both run through the same pipeline.
  if (c.shot.algorithmSource === 'backend') return 'SIMULATED SHOT — LIVE ALGORITHM FIX';
  if (c.shot.algorithmSource === 'client-fallback') return 'SIMULATED — BACKEND OFFLINE, CLIENT ESTIMATE';
  return null;
}

function DiamondBracket({ label, tag }: { label: string; tag: string | null }) {
  return (
    <div style={{ position: 'relative', width: 46, height: 46, pointerEvents: 'none' }}>
      <svg width="46" height="46" viewBox="0 0 46 46" style={{ position: 'absolute', inset: 0 }}>
        <rect
          x="18"
          y="18"
          width="10"
          height="10"
          transform="rotate(45 23 23)"
          fill="var(--hostile)"
          stroke="#fff"
          strokeWidth="0.6"
        />
        {/* corner brackets */}
        {[
          [2, 2, 2, 9, 9, 2],
          [44, 2, 44, 9, 37, 2],
          [2, 44, 2, 37, 9, 44],
          [44, 44, 44, 37, 37, 44],
        ].map(([x1, y1, x2, y2, x3, y3], i) => (
          <polyline
            key={i}
            points={`${x2},${y2} ${x1},${y1} ${x3},${y3}`}
            fill="none"
            stroke="var(--hostile)"
            strokeWidth="1.6"
          />
        ))}
      </svg>
      <div
        className="label font-mono"
        style={{
          position: 'absolute',
          top: 48,
          left: '50%',
          transform: 'translateX(-50%)',
          fontSize: 10,
          color: 'var(--hostile)',
          whiteSpace: 'nowrap',
          textShadow: '0 1px 2px #000',
        }}
      >
        {label}
        {tag && <div style={{ color: 'var(--uncertainty)', fontSize: 9 }}>{tag}</div>}
      </div>
    </div>
  );
}

// The marker sits at the confirmed ground-truth point — where you actually
// clicked, or the preset's authored location — not at the algorithm's
// reported (possibly offset) fix. That's a deliberate choice: this is the
// tactical map's "mark this as an enemy zone" pin, and it should never move
// off the point you marked. The algorithm's real, sometimes-imperfect
// numbers (direction/range/confidence) still drive Tab 2's readout and Tab
// 3's verification comparison unchanged — only the map pin here is fixed to
// truth, so the two never visually disagree on this tab.
export default function HostilesLayer() {
  const contacts = useGdsStore((s) => s.contacts);
  const tab = useGdsStore((s) => s.tab);

  if (tab === 2) return null;

  return (
    <group>
      {contacts.map((c) => (
        <Html
          key={c.runId}
          position={[c.truthEast, groundY(c.truthEast, c.truthNorth) + 6, c.truthNorth]}
          center
          zIndexRange={[15, 0]}
        >
          <DiamondBracket label={c.shot.id} tag={tagFor(c)} />
        </Html>
      ))}
    </group>
  );
}

export { DiamondBracket };
