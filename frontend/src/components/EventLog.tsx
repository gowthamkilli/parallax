import type { EventLogRow } from '../types';

export default function EventLog({ rows }: { rows: EventLogRow[] }) {
  return (
    <div className="font-mono" style={{ fontSize: 10.5, height: '100%', overflowY: 'auto' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '64px 56px 52px 44px 1fr', gap: 4, color: 'var(--hud-dim)', padding: '2px 4px', borderBottom: '1px solid var(--hud-dim)' }}>
        <span>TIME</span>
        <span>BRG</span>
        <span>RNG</span>
        <span>CONF</span>
        <span>NODES</span>
      </div>
      {rows.slice(0, 6).map((r) => (
        <div
          key={r.runId}
          style={{
            display: 'grid',
            gridTemplateColumns: '64px 56px 52px 44px 1fr',
            gap: 4,
            padding: '2px 4px',
            color: r.source === 'manual' ? 'var(--uncertainty)' : 'var(--hud-line)',
            borderBottom: '1px solid rgba(237,240,232,0.08)',
          }}
        >
          <span>{r.time}</span>
          <span>{r.bearing}</span>
          <span>{r.range}</span>
          <span>{r.confidence}</span>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.nodes}</span>
        </div>
      ))}
      {rows.length === 0 && <div style={{ color: 'var(--hud-dim)', padding: '6px 4px' }}>NO EVENTS</div>}
    </div>
  );
}
