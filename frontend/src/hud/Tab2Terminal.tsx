import { useEffect, useRef, useState } from 'react';
import { useGdsStore } from '../store';
import RadarPlot from '../components/RadarPlot';
import Compass from '../components/Compass';
import Waveform from '../components/Waveform';
import BandEnergy from '../components/BandEnergy';
import EventLog from '../components/EventLog';

function useCountUp(value: number, durationMs = 400): number {
  const [display, setDisplay] = useState(value);
  // Tracks wherever the animation currently IS, not just its start/end, so a
  // second update arriving mid-flight resumes smoothly instead of jumping
  // back to the value that was current when the first animation began.
  const latestRef = useRef(value);
  useEffect(() => {
    latestRef.current = display;
  });
  useEffect(() => {
    const from = latestRef.current;
    const start = performance.now();
    let raf: number;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / durationMs);
      const eased = 1 - (1 - p) * (1 - p);
      setDisplay(from + (value - from) * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return display;
}

export default function Tab2Terminal() {
  const contacts = useGdsStore((s) => s.contacts);
  const activeShot = useGdsStore((s) => s.activeShot);
  const eventLog = useGdsStore((s) => s.eventLog);
  const [flash, setFlash] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const lastContact = contacts[contacts.length - 1] ?? null;
  const shot = activeShot?.shot ?? lastContact?.shot ?? null;

  useEffect(() => {
    if (contacts.length === 0) return;
    setFlash(true);
    const t = window.setTimeout(() => setFlash(false), 500);
    return () => window.clearTimeout(t);
  }, [contacts.length]);

  const distance = useCountUp(shot?.distance_m ?? 0);
  const confidence = useCountUp(shot?.confidence_pct ?? 0);

  const ghosts = contacts
    .filter((c) => c.runId !== lastContact?.runId)
    .map((c) => ({ runId: c.runId, shot: c.shot, ageMs: now - c.firedAtMs }));

  const resolveTimeS = lastContact?.resolveTimeS ?? 0;

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        perspective: 1800,
        zIndex: 30,
      }}
    >
      <div
        className="font-mono"
        style={{
          width: 'min(1180px, 92vw)',
          height: 'min(700px, 82vh)',
          background: 'linear-gradient(160deg, #1b1e18, #0c0e0a)',
          border: '10px solid #23261f',
          borderRadius: 10,
          boxShadow: flash ? '0 0 0 3px var(--hostile), 0 30px 60px rgba(0,0,0,0.6)' : '0 30px 60px rgba(0,0,0,0.6)',
          transform: 'rotateY(6deg) rotateX(3deg)',
          transformStyle: 'preserve-3d',
          position: 'relative',
          display: 'flex',
          overflow: 'hidden',
          transition: 'box-shadow 120ms ease-out',
        }}
      >
        {/* screws */}
        {[[10, 10], [10, -10], [-10, 10], [-10, -10]].map(([dy, dx], i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: '#3a3d33',
              top: dy > 0 ? 8 : undefined,
              bottom: dy < 0 ? 8 : undefined,
              left: dx > 0 ? 8 : undefined,
              right: dx < 0 ? 8 : undefined,
              boxShadow: 'inset 0 1px 1px rgba(0,0,0,0.6)',
            }}
          />
        ))}

        {/* screen glare */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: 'linear-gradient(115deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0) 30%)',
            pointerEvents: 'none',
            zIndex: 5,
          }}
        />
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage:
              'repeating-linear-gradient(0deg, rgba(0,0,0,0.12) 0px, rgba(0,0,0,0.12) 1px, transparent 1px, transparent 3px)',
            pointerEvents: 'none',
            zIndex: 5,
          }}
        />

        {/* left: radar */}
        <div style={{ width: '55%', padding: 18, display: 'flex', flexDirection: 'column' }}>
          <div className="label" style={{ fontSize: 11, color: 'var(--hud-dim)', marginBottom: 6 }}>
            BEARING / RANGE
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <RadarPlot shot={shot} ghosts={ghosts} />
          </div>
        </div>

        {/* right: readout */}
        <div style={{ width: '45%', borderLeft: '1px solid var(--hud-dim)', padding: 18, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
            <span className="label" style={{ fontSize: 11, color: 'var(--hud-dim)' }}>CONTACT</span>
            <span className="label" style={{ fontSize: 13, color: 'var(--hostile)' }}>{shot?.id ?? '—'}</span>
          </div>
          {shot?.algorithmSource && (
            <div
              className="label font-mono"
              style={{
                fontSize: 9,
                marginBottom: 4,
                color: shot.algorithmSource === 'backend' ? 'var(--friendly)' : 'var(--uncertainty)',
              }}
            >
              {shot.algorithmSource === 'backend' ? 'LIVE ALGORITHM FIX' : 'BACKEND OFFLINE — CLIENT ESTIMATE'}
            </div>
          )}
          <div style={{ borderTop: '1px solid var(--hud-dim)', margin: '4px 0 10px' }} />

          {/* compass — the local reference for DIRECTION, so the bearing
              never rests on the string alone */}
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 10 }}>
            <div style={{ width: 84, height: 84, flexShrink: 0 }}>
              <Compass azimuthDeg={shot?.azimuth_deg ?? null} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <div className="label" style={{ fontSize: 10, color: 'var(--hud-dim)' }}>DIRECTION</div>
              <div style={{ fontSize: 42, fontWeight: 700, lineHeight: 1, letterSpacing: '0.02em' }}>{shot?.direction ?? '—'}</div>
              <div className="font-mono" style={{ fontSize: 11, color: 'var(--hud-dim)' }}>
                {shot ? `${shot.azimuth_deg.toFixed(1)}° TRUE` : '—'}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 24, marginBottom: 10 }}>
            <div>
              <div className="label" style={{ fontSize: 10, color: 'var(--hud-dim)' }}>DISTANCE</div>
              <div style={{ fontSize: 34, fontWeight: 700, lineHeight: 1 }}>
                {distance.toFixed(1)} <span style={{ fontSize: 14, color: 'var(--hud-dim)' }}>m</span>
              </div>
            </div>
            <div>
              <div className="label" style={{ fontSize: 10, color: 'var(--hud-dim)' }}>CONFIDENCE</div>
              <div style={{ fontSize: 34, fontWeight: 700, lineHeight: 1, color: 'var(--friendly)' }}>
                {confidence.toFixed(1)} <span style={{ fontSize: 14, color: 'var(--hud-dim)' }}>%</span>
              </div>
            </div>
          </div>

          <div style={{ borderTop: '1px solid var(--hud-dim)', margin: '4px 0 8px' }} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', rowGap: 4, fontSize: 13 }}>
            <div style={{ color: 'var(--hud-dim)' }}>LAT</div>
            <div>{shot ? `${shot.latitude.toFixed(6)} N` : '—'}</div>
            <div style={{ color: 'var(--hud-dim)' }}>LON</div>
            <div>{shot ? `${shot.longitude.toFixed(6)} E` : '—'}</div>
          </div>
          <div style={{ borderTop: '1px solid var(--hud-dim)', margin: '8px 0' }} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', rowGap: 4, fontSize: 13 }}>
            <div style={{ color: 'var(--hud-dim)' }}>REF NODE</div>
            <div>{shot?.detecting_node ?? '—'}</div>
            <div style={{ color: 'var(--hud-dim)' }}>CONTRIBUTING</div>
            <div style={{ fontSize: 11 }}>{shot?.contributing_nodes?.join(' ') ?? '—'}</div>
            <div style={{ color: 'var(--hud-dim)' }}>TDOA SPREAD</div>
            <div>{shot?.tdoa_ms ? `${Math.max(...shot.tdoa_ms).toFixed(3)} ms` : '—'}</div>
            <div style={{ color: 'var(--hud-dim)' }}>SNR</div>
            <div>{shot?.snr_db ? `${shot.snr_db.toFixed(1)} dB` : '—'}</div>
            <div style={{ color: 'var(--hud-dim)' }}>BAND</div>
            <div>150 Hz – 3.0 kHz</div>
            <div style={{ color: 'var(--hud-dim)' }}>CLASS</div>
            <div>{shot?.weapon_class ?? '—'}</div>
            <div style={{ color: 'var(--hud-dim)' }}>RESOLVE</div>
            <div>{resolveTimeS ? `${resolveTimeS.toFixed(2)} s` : '—'}</div>
          </div>

          <div style={{ flex: 1 }} />

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div>
              <div className="label" style={{ fontSize: 9, color: 'var(--hud-dim)', marginBottom: 2 }}>WAVEFORM</div>
              <div style={{ height: 46, background: '#050603', border: '1px solid var(--hud-dim)' }}>
                <Waveform shot={shot} />
              </div>
            </div>
            <div>
              <div className="label" style={{ fontSize: 9, color: 'var(--hud-dim)', marginBottom: 2 }}>BAND ENERGY</div>
              <div style={{ height: 30, background: '#050603', border: '1px solid var(--hud-dim)', padding: 3 }}>
                <BandEnergy shot={shot} />
              </div>
            </div>
            <div>
              <div className="label" style={{ fontSize: 9, color: 'var(--hud-dim)', marginBottom: 2 }}>EVENT LOG</div>
              <div style={{ height: 90, background: '#050603', border: '1px solid var(--hud-dim)' }}>
                <EventLog rows={eventLog} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
