import type { Unit, SensorNode, Personnel } from '../types';

// Deterministic PRNG so the layout is stable across reloads (no Math.random jitter).
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface UnitDef {
  id: string;
  callsign: string;
  personnelCount: number;
  centerEast: number;
  centerNorth: number;
  radius: number;
  headings: [number, number, number];
  seed: number;
}

const UNIT_DEFS: UnitDef[] = [
  { id: 'VAJRA', callsign: 'VAJRA', personnelCount: 18, centerEast: -520, centerNorth: 430, radius: 150, headings: [40, 160, 280], seed: 11 },
  { id: 'GARUD', callsign: 'GARUD', personnelCount: 17, centerEast: 640, centerNorth: 610, radius: 140, headings: [200, 320, 80], seed: 29 },
  { id: 'RUDRA', callsign: 'RUDRA', personnelCount: 16, centerEast: 60, centerNorth: -720, radius: 135, headings: [10, 130, 250], seed: 47 },
];

export const UNITS: Unit[] = UNIT_DEFS.map((u) => ({
  id: u.id,
  callsign: u.callsign,
  personnelCount: u.personnelCount,
  centerEast: u.centerEast,
  centerNorth: u.centerNorth,
  radius: u.radius,
  rssi_dbm: -55 - Math.round(u.seed % 20),
  power_pct: 78 + (u.seed % 18),
  linkStatus: 'MESH',
}));

export const NODES: SensorNode[] = UNIT_DEFS.flatMap((u) => {
  const rnd = mulberry32(u.seed * 7);
  return [0, 1, 2].map((i) => {
    const ang = rnd() * Math.PI * 2;
    const r = 25 + rnd() * 40;
    return {
      id: `${u.callsign}-${i + 1}`,
      unit: u.id,
      east: u.centerEast + Math.cos(ang) * r,
      north: u.centerNorth + Math.sin(ang) * r,
      heading_deg: u.headings[i],
      online: true,
    };
  });
});

export const PERSONNEL: Personnel[] = UNIT_DEFS.flatMap((u) => {
  const rnd = mulberry32(u.seed * 13 + 3);
  const nodeCarrierSlots = new Set([0, 1, 2]);
  return Array.from({ length: u.personnelCount }, (_, i) => {
    const ang = rnd() * Math.PI * 2;
    const r = rnd() * u.radius;
    const isNodeCarrier = nodeCarrierSlots.has(i);
    const pos = isNodeCarrier
      ? { east: NODES.find((n) => n.id === `${u.callsign}-${i + 1}`)!.east, north: NODES.find((n) => n.id === `${u.callsign}-${i + 1}`)!.north }
      : { east: u.centerEast + Math.cos(ang) * r, north: u.centerNorth + Math.sin(ang) * r };
    return {
      id: `${u.callsign}-P${i + 1}`,
      unit: u.id,
      east: pos.east,
      north: pos.north,
      isNodeCarrier,
    };
  });
});

export function nearestNodes(east: number, north: number, count: number): SensorNode[] {
  return [...NODES]
    .sort((a, b) => {
      const da = (a.east - east) ** 2 + (a.north - north) ** 2;
      const db = (b.east - east) ** 2 + (b.north - north) ** 2;
      return da - db;
    })
    .slice(0, count);
}

export function nodeById(id: string): SensorNode | undefined {
  return NODES.find((n) => n.id === id);
}
