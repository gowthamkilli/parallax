import { useEffect } from 'react';
import Scene from './scene/Scene';
import TabBar from './components/TabBar';
import ContactBanner from './components/ContactBanner';
import Tab1Hud from './hud/Tab1Hud';
import Tab2Terminal from './hud/Tab2Terminal';
import Tab3Verification from './hud/Tab3Verification';
import DevPanel from './hud/DevPanel';
import { useGdsStore } from './store';
import { checkHealth } from './lib/backend';
import { PRESET_TARGETS } from './data/presets';

function App() {
  const tab = useGdsStore((s) => s.tab);
  const setTab = useGdsStore((s) => s.setTab);
  const firePresetAtIndex = useGdsStore((s) => s.firePresetAtIndex);
  const selectedPresetIdx = useGdsStore((s) => s.selectedPresetIdx);
  const manualMode = useGdsStore((s) => s.manualMode);
  const setManualMode = useGdsStore((s) => s.setManualMode);
  const resetSession = useGdsStore((s) => s.resetSession);
  const toggleDevPanel = useGdsStore((s) => s.toggleDevPanel);
  const setBackendOnline = useGdsStore((s) => s.setBackendOnline);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const ok = await checkHealth();
      if (!cancelled) setBackendOnline(ok);
    };
    poll();
    const t = window.setInterval(poll, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [setBackendOnline]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === '1' || e.key === '2' || e.key === '3') {
        if (e.metaKey || e.ctrlKey) return;
        setTab(Number(e.key) as 1 | 2 | 3);
        return;
      }
      const num = Number(e.key);
      if (num >= 1 && num <= 9 && tab === 1) {
        const idx = num - 1;
        if (PRESET_TARGETS[idx]) firePresetAtIndex(idx);
        return;
      }
      if (e.code === 'Space') {
        e.preventDefault();
        if (PRESET_TARGETS[selectedPresetIdx]) firePresetAtIndex(selectedPresetIdx);
        return;
      }
      if (e.key === 'r' || e.key === 'R') {
        resetSession();
        return;
      }
      if (e.key === 'm' || e.key === 'M') {
        setManualMode(!manualMode);
        return;
      }
      if (e.key === 'd' || e.key === 'D') {
        toggleDevPanel();
        return;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [tab, selectedPresetIdx, manualMode, setTab, firePresetAtIndex, resetSession, setManualMode, toggleDevPanel]);

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'var(--bg)', overflow: 'hidden' }}>
      <Scene />

      {/* vignette + grain + chromatic aberration edge — cheap CSS post, no shader passes */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 15,
          boxShadow: 'inset 0 0 220px rgba(0,0,0,0.75)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 15,
          opacity: 0.05,
          mixBlendMode: 'overlay',
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
        }}
      />

      <TabBar />
      <ContactBanner />

      {tab === 1 && <Tab1Hud />}
      {tab === 2 && <Tab2Terminal />}
      {tab === 3 && <Tab3Verification />}

      <DevPanel />

      <div
        className="font-mono"
        style={{
          position: 'absolute',
          bottom: 6,
          right: 10,
          fontSize: 9,
          color: 'var(--hud-dim)',
          zIndex: 20,
          pointerEvents: 'none',
        }}
      >
        SIMULATED DATA — GDS DEMO BUILD
      </div>
    </div>
  );
}

export default App;
