import { useEffect, useState } from 'react';
import { useGdsStore } from '../store';

function TickLadder({ orientation, style }: { orientation: 'v' | 'h'; style: React.CSSProperties }) {
  const ticks = Array.from({ length: 14 });
  return (
    <div style={{ position: 'absolute', display: 'flex', flexDirection: orientation === 'v' ? 'column' : 'row', gap: 8, ...style }}>
      {ticks.map((_, i) => (
        <div
          key={i}
          style={{
            background: 'var(--hud-dim)',
            width: orientation === 'v' ? (i % 3 === 0 ? 14 : 8) : 1,
            height: orientation === 'v' ? 1 : i % 3 === 0 ? 14 : 8,
          }}
        />
      ))}
    </div>
  );
}

function CornerBrackets() {
  const c = 'var(--hud-dim)';
  const size = 30;
  const positions = [
    { top: 60, left: 16, borderTop: `2px solid ${c}`, borderLeft: `2px solid ${c}` },
    { top: 60, right: 16, borderTop: `2px solid ${c}`, borderRight: `2px solid ${c}` },
    { bottom: 16, left: 16, borderBottom: `2px solid ${c}`, borderLeft: `2px solid ${c}` },
    { bottom: 16, right: 16, borderBottom: `2px solid ${c}`, borderRight: `2px solid ${c}` },
  ];
  return (
    <>
      {positions.map((p, i) => (
        <div key={i} style={{ position: 'absolute', width: size, height: size, ...p }} />
      ))}
    </>
  );
}

export default function Tab1Hud() {
  const presets = useGdsStore((s) => s.presets);
  const fireShot = useGdsStore((s) => s.fireShot);
  const manualMode = useGdsStore((s) => s.manualMode);
  const setManualMode = useGdsStore((s) => s.setManualMode);
  const selectedPresetIdx = useGdsStore((s) => s.selectedPresetIdx);
  const setSelectedPresetIdx = useGdsStore((s) => s.setSelectedPresetIdx);
  const [clock, setClock] = useState(new Date());

  useEffect(() => {
    const t = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);

  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 20 }}>
      <CornerBrackets />

      {/* top-left REC indicator */}
      <div className="font-mono" style={{ position: 'absolute', top: 20, left: 20, display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: 'var(--rec-red)',
            animation: 'pulse 1.4s ease-in-out infinite',
          }}
        />
        REC · {clock.toLocaleTimeString('en-GB', { hour12: false })}
      </div>

      {/* zoom indicator */}
      <div className="font-mono" style={{ position: 'absolute', top: 20, left: 130, fontSize: 13 }}>1X</div>

      {/* center-top altitude readout */}
      <div className="label font-mono" style={{ position: 'absolute', top: 20, left: '50%', transform: 'translateX(-50%)', fontSize: 13 }}>
        AO {`—`} {presets.length} CONTACTS PRESET
      </div>

      {/* top-right */}
      <div className="label font-mono" style={{ position: 'absolute', top: 20, right: 20, fontSize: 13, textAlign: 'right' }}>
        SENSOR NET · 9 NODES ONLINE
      </div>

      <TickLadder orientation="v" style={{ left: 6, top: '20%', height: '55%' }} />
      <TickLadder orientation="v" style={{ right: 6, top: '20%', height: '55%' }} />
      <TickLadder orientation="h" style={{ bottom: 90, left: '25%', width: '50%' }} />

      {/* center reticle */}
      <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', width: 40, height: 40 }}>
        <div style={{ position: 'absolute', top: '50%', left: 0, width: 14, height: 1, background: 'var(--hud-dim)' }} />
        <div style={{ position: 'absolute', top: '50%', right: 0, width: 14, height: 1, background: 'var(--hud-dim)' }} />
        <div style={{ position: 'absolute', left: '50%', top: 0, height: 14, width: 1, background: 'var(--hud-dim)' }} />
        <div style={{ position: 'absolute', left: '50%', bottom: 0, height: 14, width: 1, background: 'var(--hud-dim)' }} />
      </div>

      {/* manual mode toggle + tag */}
      <div style={{ position: 'absolute', top: 60, right: 20, pointerEvents: 'auto' }}>
        <button
          onClick={() => setManualMode(!manualMode)}
          className="label font-mono"
          style={{
            background: manualMode ? 'var(--uncertainty)' : 'var(--panel)',
            color: manualMode ? '#0a0d09' : 'var(--hud-dim)',
            border: '1px solid var(--hud-dim)',
            fontSize: 11,
            padding: '4px 10px',
            cursor: 'pointer',
          }}
        >
          {manualMode ? 'MANUAL — CLICK TERRAIN TO PLACE' : 'MANUAL MODE [M]'}
        </button>
      </div>

      {/* preset tray */}
      <div
        className="font-mono"
        style={{
          position: 'absolute',
          bottom: 16,
          left: '50%',
          transform: 'translateX(-50%)',
          display: 'flex',
          gap: 4,
          maxWidth: '92vw',
          overflowX: 'auto',
          pointerEvents: 'auto',
          background: 'var(--panel)',
          padding: 6,
          border: '1px solid var(--hud-dim)',
        }}
      >
        {presets.map((p, i) => (
          <button
            key={p.id}
            onClick={() => {
              setSelectedPresetIdx(i);
              fireShot(p);
            }}
            style={{
              background: 'transparent',
              color: 'var(--hud-line)',
              border: selectedPresetIdx === i ? '1px solid var(--friendly)' : '1px solid var(--hud-dim)',
              padding: '6px 10px',
              fontSize: 11,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              textAlign: 'left',
            }}
            title={p.label}
          >
            <div style={{ color: 'var(--friendly)' }}>{i < 9 ? `[${i + 1}]` : ''} {p.id}</div>
            <div style={{ color: 'var(--hud-dim)', fontSize: 10 }}>{p.label}</div>
          </button>
        ))}
      </div>

      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.2} }`}</style>
    </div>
  );
}
