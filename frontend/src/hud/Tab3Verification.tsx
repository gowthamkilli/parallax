import { motion } from 'framer-motion';
import { useGdsStore } from '../store';
import { computeSessionStats } from '../lib/stats';
import { compassBearing } from '../geo';

function angDelta(a: number, b: number): number {
  let d = a - b;
  while (d > 180) d -= 360;
  while (d < -180) d += 360;
  return Math.abs(d);
}

export default function Tab3Verification() {
  const contacts = useGdsStore((s) => s.contacts);
  const verificationIdx = useGdsStore((s) => s.verificationIdx);
  const setVerificationIdx = useGdsStore((s) => s.setVerificationIdx);

  const contact = verificationIdx >= 0 && verificationIdx < contacts.length ? contacts[verificationIdx] : null;
  const stats = computeSessionStats(contacts);

  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 30 }}>
      {/* stepper */}
      {contacts.length > 0 && (
        <div
          className="font-mono"
          style={{
            position: 'absolute',
            top: 64,
            left: '50%',
            transform: 'translateX(-50%)',
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            pointerEvents: 'auto',
            background: 'var(--panel)',
            border: '1px solid var(--hud-dim)',
            padding: '6px 10px',
          }}
        >
          <button
            onClick={() => setVerificationIdx(Math.max(0, verificationIdx - 1))}
            style={{ background: 'none', border: 'none', color: 'var(--hud-line)', cursor: 'pointer', fontSize: 14 }}
          >
            ◀
          </button>
          <span style={{ fontSize: 12 }}>
            {contact ? `${contact.shot.id} — ${verificationIdx + 1} / ${contacts.length}` : 'NO CONTACTS'}
          </span>
          <button
            onClick={() => setVerificationIdx(Math.min(contacts.length - 1, verificationIdx + 1))}
            style={{ background: 'none', border: 'none', color: 'var(--hud-line)', cursor: 'pointer', fontSize: 14 }}
          >
            ▶
          </button>
        </div>
      )}

      {/* results card */}
      {contact && (
        <motion.div
          initial={{ y: 60, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 1.2, duration: 0.5, ease: 'easeOut' }}
          className="font-mono"
          style={{
            position: 'absolute',
            bottom: 90,
            left: 20,
            background: 'var(--panel)',
            border: '1px solid var(--hud-dim)',
            padding: 14,
            fontSize: 12,
            minWidth: 340,
            pointerEvents: 'auto',
          }}
        >
          {contact.shot.truth ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr 1fr 1fr', gap: 4, marginBottom: 6 }}>
                <div />
                <div style={{ color: 'var(--hud-dim)' }}>TRUE</div>
                <div style={{ color: 'var(--hud-dim)' }}>REPORTED</div>
                <div style={{ color: 'var(--hud-dim)' }}>ERROR</div>
                <div style={{ color: 'var(--hud-dim)' }}>BEARING</div>
                <div>{compassBearing(contact.shot.truth.azimuth_deg)}</div>
                <div>{contact.shot.direction}</div>
                <div style={{ color: 'var(--uncertainty)' }}>{angDelta(contact.shot.azimuth_deg, contact.shot.truth.azimuth_deg).toFixed(1)}°</div>
                <div style={{ color: 'var(--hud-dim)' }}>RANGE</div>
                <div>{contact.shot.truth.distance_m.toFixed(1)} m</div>
                <div>{contact.shot.distance_m.toFixed(1)} m</div>
                <div style={{ color: 'var(--uncertainty)' }}>
                  {Math.abs(contact.shot.distance_m - contact.shot.truth.distance_m).toFixed(1)} m
                </div>
                <div style={{ color: 'var(--hud-dim)' }}>CONFIDENCE</div>
                <div />
                <div style={{ color: 'var(--friendly)' }}>{contact.shot.confidence_pct.toFixed(1)}%</div>
                <div />
              </div>
            </>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', rowGap: 4 }}>
              <div className="label" style={{ color: 'var(--hud-dim)', gridColumn: '1 / -1', marginBottom: 4 }}>RESOLVED FIX</div>
              <div style={{ color: 'var(--hud-dim)' }}>BEARING</div>
              <div>{contact.shot.direction} FROM {contact.shot.detecting_node}</div>
              <div style={{ color: 'var(--hud-dim)' }}>RANGE</div>
              <div>{contact.shot.distance_m.toFixed(1)} m</div>
              <div style={{ color: 'var(--hud-dim)' }}>POSITION</div>
              <div>{contact.shot.latitude.toFixed(6)} N {contact.shot.longitude.toFixed(6)} E</div>
              <div style={{ color: 'var(--hud-dim)' }}>CONFIDENCE</div>
              <div style={{ color: 'var(--friendly)' }}>{contact.shot.confidence_pct.toFixed(1)}%</div>
              <div style={{ color: 'var(--hud-dim)' }}>RESOLVE TIME</div>
              <div>{contact.resolveTimeS.toFixed(2)} s</div>
            </div>
          )}
        </motion.div>
      )}

      {/* session statistics */}
      {stats.count > 0 && (
        <div
          className="font-mono"
          style={{
            position: 'absolute',
            bottom: 90,
            right: 20,
            background: 'var(--panel)',
            border: '1px solid var(--hud-dim)',
            padding: 14,
            fontSize: 12,
            minWidth: 300,
            pointerEvents: 'auto',
          }}
        >
          <div className="label" style={{ color: 'var(--hud-dim)', marginBottom: 6 }}>SESSION STATISTICS</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', rowGap: 4 }}>
            <span style={{ color: 'var(--hud-dim)' }}>CONTACTS RESOLVED</span>
            <span>{stats.count}</span>
            <span style={{ color: 'var(--hud-dim)' }}>MEAN CONFIDENCE</span>
            <span>{stats.meanConfidence.toFixed(1)} %</span>
            <span style={{ color: 'var(--hud-dim)' }}>MEAN RESOLVE TIME</span>
            <span>{stats.meanResolveTime.toFixed(2)} s</span>
            <span style={{ color: 'var(--hud-dim)' }}>BEARING SPREAD</span>
            <span>{stats.bearingMin.toFixed(0)}° – {stats.bearingMax.toFixed(0)}°</span>
            {stats.hasTruth && (
              <>
                <span style={{ color: 'var(--hud-dim)' }}>MEAN BEARING ERROR</span>
                <span style={{ color: 'var(--uncertainty)' }}>{stats.meanBearingError!.toFixed(1)}°</span>
                <span style={{ color: 'var(--hud-dim)' }}>MEAN RANGE ERROR</span>
                <span style={{ color: 'var(--uncertainty)' }}>{stats.meanRangeErrorPct!.toFixed(1)}%</span>
                <span style={{ color: 'var(--hud-dim)' }}>CEP50</span>
                <span style={{ color: 'var(--uncertainty)' }}>{stats.cep50!.toFixed(1)} m</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
