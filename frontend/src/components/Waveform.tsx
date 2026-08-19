import { useEffect, useRef } from 'react';
import type { PresetShot } from '../types';

function synthSamples(shot: PresetShot, n = 400): Float32Array {
  const out = new Float32Array(n);
  const amp = Math.min(1, Math.max(0.2, (shot.snr_db ?? 15) / 26));
  const crackAt = Math.floor(n * 0.28);
  const blastAt = Math.floor(n * 0.5);
  for (let i = 0; i < n; i++) {
    let v = (Math.sin(i * 0.9) + Math.sin(i * 2.3) + Math.sin(i * 5.1)) * 0.02;
    const dCrack = i - crackAt;
    v += amp * 0.9 * Math.exp(-((dCrack / 4) ** 2)) * Math.sign(Math.sin(dCrack * 1.8));
    const dBlast = i - blastAt;
    v += amp * Math.exp(-((dBlast / 22) ** 2)) * Math.sin(dBlast * 0.35) * 0.8;
    out[i] = v;
  }
  return out;
}

export default function Waveform({ shot }: { shot: PresetShot | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !shot) return;
    const ctx = canvas.getContext('2d')!;
    const w = canvas.width;
    const h = canvas.height;
    const samples = synthSamples(shot);
    const start = performance.now();

    const draw = (t: number) => {
      const reveal = Math.min(1, (t - start) / 550);
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = '#e8d24a';
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      const count = Math.floor(samples.length * reveal);
      for (let i = 0; i < count; i++) {
        const x = (i / samples.length) * w;
        const y = h / 2 - samples[i] * (h / 2.4);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      ctx.strokeStyle = 'rgba(237,240,232,0.25)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, h / 2);
      ctx.lineTo(w, h / 2);
      ctx.stroke();

      if (reveal < 1) rafRef.current = requestAnimationFrame(draw);
    };
    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [shot?.id]);

  const reconstructed = !shot?.tdoa_ms;

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <canvas ref={canvasRef} width={520} height={90} style={{ width: '100%', height: '100%', display: 'block' }} />
      <div className="font-mono" style={{ position: 'absolute', top: 2, left: 4, fontSize: 9, color: 'var(--hud-dim)' }}>
        CRACK <span style={{ color: '#e8d24a' }}>·</span> BLAST
      </div>
      {reconstructed && (
        <div
          className="label font-mono"
          style={{ position: 'absolute', top: 2, right: 4, fontSize: 9, color: 'var(--uncertainty)' }}
        >
          RECONSTRUCTED
        </div>
      )}
    </div>
  );
}
