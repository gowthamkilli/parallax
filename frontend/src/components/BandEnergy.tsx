import { useEffect, useRef, useState } from 'react';
import type { PresetShot } from '../types';

const BANDS = 8;

export default function BandEnergy({ shot }: { shot: PresetShot | null }) {
  const [levels, setLevels] = useState<number[]>(new Array(BANDS).fill(0.04));
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (!shot) return;
    const amp = Math.min(1, Math.max(0.3, (shot.snr_db ?? 15) / 26));
    const peaks = Array.from({ length: BANDS }, (_, i) => {
      const centerBias = 1 - Math.abs(i - BANDS / 2.2) / (BANDS / 2);
      return Math.max(0.08, amp * (0.4 + centerBias * 0.6) * (0.7 + Math.random() * 0.5));
    });
    const start = performance.now();
    const animate = (t: number) => {
      const elapsed = t - start;
      const rise = Math.min(1, elapsed / 140);
      const decay = elapsed > 140 ? Math.exp(-(elapsed - 140) / 900) : 1;
      setLevels(peaks.map((p) => 0.04 + p * rise * decay));
      if (elapsed < 2200) rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [shot?.id]);

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: '100%', width: '100%' }}>
      {levels.map((l, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            height: `${Math.min(100, l * 100)}%`,
            background: l > 0.6 ? 'var(--hostile)' : 'var(--friendly)',
            opacity: 0.85,
            transition: 'height 60ms linear',
          }}
        />
      ))}
    </div>
  );
}
