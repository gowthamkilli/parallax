import { useGdsStore } from '../store';
import type { TabId } from '../types';

const TABS: { id: TabId; label: string }[] = [
  { id: 1, label: 'TACTICAL' },
  { id: 2, label: 'DETECTION TERMINAL' },
  { id: 3, label: 'VERIFICATION' },
];

export default function TabBar() {
  const tab = useGdsStore((s) => s.tab);
  const setTab = useGdsStore((s) => s.setTab);

  return (
    <div
      className="font-mono"
      style={{
        position: 'absolute',
        top: 10,
        left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex',
        gap: 1,
        zIndex: 50,
        pointerEvents: 'auto',
      }}
    >
      {TABS.map((t) => (
        <button
          key={t.id}
          onClick={() => setTab(t.id)}
          className="label"
          style={{
            background: tab === t.id ? 'var(--hud-line)' : 'var(--panel)',
            color: tab === t.id ? '#0a0d09' : 'var(--hud-dim)',
            border: '1px solid var(--hud-dim)',
            padding: '6px 16px',
            fontSize: 12,
            cursor: 'pointer',
            letterSpacing: '0.1em',
          }}
        >
          {t.id} · {t.label}
        </button>
      ))}
    </div>
  );
}
