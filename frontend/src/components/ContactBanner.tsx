import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useGdsStore } from '../store';

export default function ContactBanner() {
  const contacts = useGdsStore((s) => s.contacts);
  const [visibleRunId, setVisibleRunId] = useState<string | null>(null);

  useEffect(() => {
    if (contacts.length === 0) return;
    const last = contacts[contacts.length - 1];
    setVisibleRunId(last.runId);
    const t = window.setTimeout(() => setVisibleRunId(null), 2600);
    return () => window.clearTimeout(t);
  }, [contacts.length]);

  const contact = contacts.find((c) => c.runId === visibleRunId);

  return (
    <AnimatePresence>
      {contact && (
        <motion.div
          initial={{ y: -60, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: -60, opacity: 0 }}
          transition={{ duration: 0.35, ease: 'easeOut' }}
          style={{
            position: 'absolute',
            top: 54,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 60,
            background: 'var(--panel)',
            border: '1px solid var(--hostile)',
            padding: '8px 22px',
            display: 'flex',
            gap: 20,
            alignItems: 'baseline',
            pointerEvents: 'none',
          }}
        >
          <span className="label" style={{ color: 'var(--hostile)', fontSize: 18, fontWeight: 700 }}>
            CONTACT
          </span>
          <span className="font-mono" style={{ fontSize: 13, color: 'var(--hud-line)' }}>
            BRG {contact.shot.direction}
          </span>
          <span className="font-mono" style={{ fontSize: 13, color: 'var(--hud-line)' }}>
            RNG {contact.shot.distance_m.toFixed(0)}m
          </span>
          {contact.source === 'manual' && (
            <span className="font-mono" style={{ fontSize: 11, color: 'var(--uncertainty)' }}>
              SIMULATED
            </span>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
