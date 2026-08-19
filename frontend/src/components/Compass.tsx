import { useEffect, useRef } from 'react';

const CX = 70;
const CY = 70;
const R = 60;

function wrapDelta(delta: number): number {
  // Shortest angular path so the needle never spins the long way round a
  // 359deg -> 2deg transition.
  let d = delta % 360;
  if (d > 180) d -= 360;
  if (d < -180) d += 360;
  return d;
}

const TICKS = Array.from({ length: 36 }, (_, i) => i * 10);
const CARDINALS: [number, string][] = [
  [0, 'N'],
  [90, 'E'],
  [180, 'S'],
  [270, 'W'],
];

export default function Compass({ azimuthDeg }: { azimuthDeg: number | null }) {
  const needleRef = useRef<SVGGElement>(null);
  const currentRef = useRef(azimuthDeg ?? 0);

  useEffect(() => {
    if (azimuthDeg === null) return;
    const target = currentRef.current + wrapDelta(azimuthDeg - currentRef.current);
    const start = currentRef.current;
    const startT = performance.now();
    const duration = 500;
    let raf: number;
    const tick = (t: number) => {
      const p = Math.min(1, (t - startT) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      currentRef.current = start + (target - start) * eased;
      if (needleRef.current) {
        needleRef.current.setAttribute('transform', `rotate(${currentRef.current} ${CX} ${CY})`);
      }
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [azimuthDeg]);

  return (
    <svg viewBox="0 0 140 140" style={{ width: '100%', height: '100%' }}>
      <circle cx={CX} cy={CY} r={R} fill="#050603" stroke="var(--hud-dim)" strokeWidth="1" />
      <circle cx={CX} cy={CY} r={R - 14} fill="none" stroke="var(--hud-dim)" strokeWidth="0.5" opacity="0.5" />

      {TICKS.map((deg) => {
        const major = deg % 90 === 0;
        const mid = deg % 30 === 0;
        const len = major ? 12 : mid ? 8 : 4;
        const rad = ((deg - 90) * Math.PI) / 180;
        const x1 = CX + Math.cos(rad) * R;
        const y1 = CY + Math.sin(rad) * R;
        const x2 = CX + Math.cos(rad) * (R - len);
        const y2 = CY + Math.sin(rad) * (R - len);
        return (
          <line
            key={deg}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            stroke={major ? 'var(--hud-line)' : 'var(--hud-dim)'}
            strokeWidth={major ? 1.4 : 0.8}
          />
        );
      })}

      {CARDINALS.map(([deg, label]) => {
        const rad = ((deg - 90) * Math.PI) / 180;
        const x = CX + Math.cos(rad) * (R - 24);
        const y = CY + Math.sin(rad) * (R - 24);
        return (
          <text
            key={label}
            x={x}
            y={y}
            fill={label === 'N' ? 'var(--hostile)' : 'var(--hud-line)'}
            fontSize="13"
            fontWeight={700}
            textAnchor="middle"
            dominantBaseline="central"
            fontFamily="var(--font-label)"
          >
            {label}
          </text>
        );
      })}

      {/* needle */}
      <g ref={needleRef} transform={`rotate(${azimuthDeg ?? 0} ${CX} ${CY})`}>
        <polygon points={`${CX},${CY - R + 20} ${CX - 5},${CY} ${CX + 5},${CY}`} fill="var(--hostile)" />
        <polygon points={`${CX},${CY + 16} ${CX - 4},${CY} ${CX + 4},${CY}`} fill="var(--hud-dim)" />
      </g>
      <circle cx={CX} cy={CY} r="3.5" fill="var(--hud-line)" stroke="#050603" strokeWidth="1" />
    </svg>
  );
}
