import type { PresetShot } from '../types';
import { nodeById, nearestNodes } from './layout';
import { projectBearing, toLatLon, compassBearing } from '../geo';

interface Def {
  id: string;
  label: string;
  node: string;
  azimuth: number;
  distance: number;
  confidence: number;
  snr: number;
  weapon: string;
  truthAzimuth?: number;
  truthDistance?: number;
}

// 12 preset gunshot detections, hand-authored bearings so the geometry reads
// clean against the AO. In production these 12-15 entries arrive verbatim
// from the backend via window.GDS.loadPresets().
const DEFS: Def[] = [
  { id: 'DET-001', label: 'TREE LINE, EAST APPROACH', node: 'VAJRA-2', azimuth: 42.0, distance: 300.1, confidence: 87.3, snr: 18.4, weapon: '5.56x45 RIFLE', truthAzimuth: 41.1, truthDistance: 302.4 },
  { id: 'DET-002', label: 'RIDGE NORTH OF AO', node: 'GARUD-1', azimuth: 305.4, distance: 512.8, confidence: 74.6, snr: 13.1, weapon: '7.62x39 RIFLE', truthAzimuth: 306.9, truthDistance: 498.0 },
  { id: 'DET-003', label: 'OPEN GROUND, SOUTH FLANK', node: 'RUDRA-3', azimuth: 168.2, distance: 244.5, confidence: 91.8, snr: 21.7, weapon: '5.56x45 RIFLE', truthAzimuth: 168.9, truthDistance: 241.0 },
  { id: 'DET-004', label: 'SCRUB BELT, WEST', node: 'VAJRA-1', azimuth: 251.7, distance: 388.9, confidence: 68.2, snr: 10.9, weapon: 'UNCLASSIFIED', truthAzimuth: 249.0, truthDistance: 402.5 },
  { id: 'DET-005', label: 'TRACK JUNCTION, NE', node: 'GARUD-3', azimuth: 61.3, distance: 176.4, confidence: 95.1, snr: 24.3, weapon: '5.56x45 RIFLE', truthAzimuth: 61.0, truthDistance: 175.1 },
  { id: 'DET-006', label: 'CANOPY EDGE, FAR NORTH', node: 'GARUD-2', azimuth: 349.6, distance: 623.0, confidence: 58.9, snr: 8.4, weapon: 'UNCLASSIFIED', truthAzimuth: 344.2, truthDistance: 640.7 },
  { id: 'DET-007', label: 'CREEK BED, SE', node: 'RUDRA-1', azimuth: 118.5, distance: 205.2, confidence: 89.0, snr: 19.6, weapon: '7.62x39 RIFLE', truthAzimuth: 119.4, truthDistance: 201.8 },
  { id: 'DET-008', label: 'STRUCTURE CLUSTER, W', node: 'VAJRA-3', azimuth: 279.9, distance: 341.6, confidence: 81.4, snr: 15.2, weapon: '5.56x45 RIFLE', truthAzimuth: 280.6, truthDistance: 336.9 },
  { id: 'DET-009', label: 'TREE LINE, FAR EAST', node: 'GARUD-1', azimuth: 88.1, distance: 455.3, confidence: 71.0, snr: 12.0, weapon: 'UNCLASSIFIED', truthAzimuth: 89.8, truthDistance: 447.6 },
  { id: 'DET-010', label: 'OPEN PLAIN, CENTRAL', node: 'RUDRA-2', azimuth: 22.7, distance: 288.0, confidence: 93.6, snr: 22.9, weapon: '5.56x45 RIFLE', truthAzimuth: 22.3, truthDistance: 289.9 },
  { id: 'DET-011', label: 'RIDGE, SOUTH WEST', node: 'VAJRA-2', azimuth: 202.4, distance: 367.1, confidence: 64.7, snr: 9.8, weapon: '7.62x39 RIFLE', truthAzimuth: 205.1, truthDistance: 359.0 },
  { id: 'DET-012', label: 'TRACK, NORTH APPROACH', node: 'GARUD-3', azimuth: 355.0, distance: 233.9, confidence: 97.2, snr: 26.0, weapon: '5.56x45 RIFLE', truthAzimuth: 355.3, truthDistance: 232.5 },
];

function synthTdoa(distance: number, contributing: string[]): number[] {
  // Plausible pairwise spread from array baselines; marked RECONSTRUCTED when
  // the backend doesn't supply tdoa_ms directly.
  const base = Math.min(0.9, 0.15 + distance / 1400);
  return contributing.map((_, i) => (i === 0 ? 0 : +(base * (0.4 + i * 0.35)).toFixed(3)));
}

export const PRESETS: PresetShot[] = DEFS.map((d, i) => {
  const node = nodeById(d.node)!;
  const pos = projectBearing(node.east, node.north, d.azimuth, d.distance);
  const { latitude, longitude } = toLatLon(pos.east, pos.north);
  const contributing = nearestNodes(pos.east, pos.north, 3).map((n) => n.id);
  return {
    id: d.id,
    label: d.label,
    t_offset_ms: i * 1800,
    direction: compassBearing(d.azimuth),
    azimuth_deg: d.azimuth,
    distance_m: d.distance,
    latitude,
    longitude,
    confidence_pct: d.confidence,
    detecting_node: d.node,
    contributing_nodes: contributing,
    tdoa_ms: synthTdoa(d.distance, contributing),
    snr_db: d.snr,
    weapon_class: d.weapon,
    truth:
      d.truthAzimuth !== undefined
        ? { azimuth_deg: d.truthAzimuth, distance_m: d.truthDistance! }
        : undefined,
  };
});
