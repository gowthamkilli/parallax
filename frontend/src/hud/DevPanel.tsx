import { useRef, useState } from 'react';
import { useGdsStore } from '../store';
import { AO } from '../geo';
import { PRESET_TARGETS } from '../data/presets';

export default function DevPanel() {
  const devPanelOpen = useGdsStore((s) => s.devPanelOpen);
  const presets = useGdsStore((s) => s.presets);
  const loadPresets = useGdsStore((s) => s.loadPresets);
  const firePresetAtIndex = useGdsStore((s) => s.firePresetAtIndex);
  const resetSession = useGdsStore((s) => s.resetSession);
  const audioEnabled = useGdsStore((s) => s.audioEnabled);
  const setAudioEnabled = useGdsStore((s) => s.setAudioEnabled);
  const fileRef = useRef<HTMLInputElement>(null);
  const [replaying, setReplaying] = useState(false);

  if (!devPanelOpen) return null;

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    try {
      const json = JSON.parse(text);
      loadPresets(json);
    } catch {
      // ignore malformed file — dev-only affordance
    }
  };

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(presets, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'presets.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  const replaySequence = async () => {
    setReplaying(true);
    for (let i = 0; i < PRESET_TARGETS.length; i++) {
      await firePresetAtIndex(i);
      await new Promise((r) => setTimeout(r, 3200));
    }
    setReplaying(false);
  };

  return (
    <div
      className="font-mono"
      style={{
        position: 'absolute',
        top: 60,
        left: 20,
        background: 'var(--panel)',
        border: '1px solid var(--grid-blue)',
        padding: 12,
        fontSize: 11,
        zIndex: 90,
        width: 260,
        pointerEvents: 'auto',
      }}
    >
      <div className="label" style={{ color: 'var(--grid-blue)', marginBottom: 8 }}>DEV PANEL [D]</div>
      <div style={{ marginBottom: 8, color: 'var(--hud-dim)' }}>
        AO {AO.designator}
        <br />
        {AO.anchor_lat.toFixed(6)}, {AO.anchor_lon.toFixed(6)}
        <br />
        EXTENT {AO.extent_m} m
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <button onClick={() => fileRef.current?.click()} style={btnStyle}>LOAD EXTERNAL FEED.JSON</button>
        <input ref={fileRef} type="file" accept="application/json" onChange={handleFile} style={{ display: 'none' }} />
        <button onClick={handleExport} style={btnStyle}>EXPORT EXTERNAL FEED.JSON ({presets.length})</button>
        <button onClick={replaySequence} disabled={replaying} style={btnStyle}>
          {replaying ? 'REPLAYING…' : `REPLAY PRESET LIBRARY (${PRESET_TARGETS.length})`}
        </button>
        <button onClick={resetSession} style={btnStyle}>RESET SESSION [R]</button>
        <button onClick={() => setAudioEnabled(!audioEnabled)} style={btnStyle}>
          AUDIO {audioEnabled ? 'ON' : 'OFF'}
        </button>
      </div>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  background: 'transparent',
  border: '1px solid var(--hud-dim)',
  color: 'var(--hud-line)',
  padding: '6px 8px',
  fontSize: 11,
  cursor: 'pointer',
  textAlign: 'left',
};
