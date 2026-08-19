import { useEffect, useState } from 'react';
import type { PresetShot } from '../types';

const RINGS = [100, 200, 300, 400];
const MAX_RANGE = 400;
const CX = 150;
const CY = 150;
const R = 128;

function confHalfWidthDeg(conf: number): number {
  const t = Math.max(0, Math.min(1, (100 - conf) / 30));
  return 2 + t * 10;
}

function polar(azDeg: number, rangeM: number) {
  const r = Math.min(rangeM, MAX_RANGE) * (R / MAX_RANGE);
  const rad = ((azDeg - 90) * Math.PI) / 180;
  return { x: CX + Math.cos(rad) * r, y: CY + Math.sin(rad) * r };
}

interface Ghost {
  runId: string;
  shot: PresetShot;
  ageMs: number;
}

export default function RadarPlot({ shot, ghosts }: { shot: PresetShot | null; ghosts: Ghost[] }) {
  const [sweep, setSweep] = useState(0);
  useEffect(() => {
    let raf: number;
    const start = performance.now();
    const tick = (t: number) => {
      setSweep(((t - start) / 4000) * 360);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const needle = shot ? polar(shot.azimuth_deg, shot.distance_m) : null;
  const hw = shot ? confHalfWidthDeg(shot.confidence_pct) : 0;
  const wedgeA = shot ? polar(shot.azimuth_deg - hw, MAX_RANGE) : null;
  const wedgeB = shot ? polar(shot.azimuth_deg + hw, MAX_RANGE) : null;

  return (
    <svg viewBox="0 0 300 300" style={{ width: '100%', height: '100%' }}>
      <defs>
        <radialGradient id="radarBg" cx="50%" cy="50%" r="70%">
          <stop offset="0%" stopColor="#131a10" />
          <stop offset="100%" stopColor="#0a0d09" />
        </radialGradient>
      </defs>
      <circle cx={CX} cy={CY} r={R} fill="url(#radarBg)" stroke="var(--hud-dim)" strokeWidth="1" />

      {/* confidence wedge */}
      {shot && wedgeA && wedgeB && (
        <path
          d={`M ${CX} ${CY} L ${wedgeA.x} ${wedgeA.y} A ${R} ${R} 0 0 1 ${wedgeB.x} ${wedgeB.y} Z`}
          fill="var(--uncertainty)"
          opacity="0.18"
        />
      )}

      {RINGS.map((r) => (
        <g key={r}>
          <circle cx={CX} cy={CY} r={(r / MAX_RANGE) * R} fill="none" stroke="var(--hud-dim)" strokeWidth="0.6" />
          <text x={CX + 4} y={CY - (r / MAX_RANGE) * R - 2} fill="var(--hud-dim)" fontSize="7" fontFamily="var(--font-mono)">
            {r}
          </text>
        </g>
      ))}
      {/* crosshair */}
      <line x1={CX} y1={CY - R} x2={CX} y2={CY + R} stroke="var(--hud-dim)" strokeWidth="0.5" />
      <line x1={CX - R} y1={CY} x2={CX + R} y2={CY} stroke="var(--hud-dim)" strokeWidth="0.5" />
      <text x={CX} y={CY - R - 4} fill="var(--hud-dim)" fontSize="9" textAnchor="middle" fontFamily="var(--font-label)">N</text>

      {/* sweep */}
      <g opacity="0.5">
        <line
          x1={CX}
          y1={CY}
          x2={CX + Math.cos(((sweep - 90) * Math.PI) / 180) * R}
          y2={CY + Math.sin(((sweep - 90) * Math.PI) / 180) * R}
          stroke="var(--friendly)"
          strokeWidth="1"
        />
      </g>

      {/* ghosts */}
      {ghosts.map((g) => {
        const p = polar(g.shot.azimuth_deg, g.shot.distance_m);
        const fade = Math.max(0, 1 - g.ageMs / 30000);
        if (fade <= 0) return null;
        return <circle key={g.runId} cx={p.x} cy={p.y} r="3" fill="var(--hostile)" opacity={fade * 0.35} />;
      })}

      {/* needle + contact dot */}
      {shot && needle && (
        <>
          <line x1={CX} y1={CY} x2={needle.x} y2={needle.y} stroke="var(--hostile)" strokeWidth="1.4" />
          <circle cx={needle.x} cy={needle.y} r="5" fill="var(--hostile)">
            <animate attributeName="opacity" values="1;0.35;1" dur="1.1s" repeatCount="indefinite" />
          </circle>
        </>
      )}
    </svg>
  );
}
