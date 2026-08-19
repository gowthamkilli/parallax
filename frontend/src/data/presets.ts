// The local demo library: 12 hand-placed ground-truth points, one per
// hostile scenario. Nothing about direction/distance/confidence is baked in
// here anymore — firing one runs the exact same forwardSim -> real backend
// pipeline as a manual grid click (see store.fireGroundTruth), so what the
// dashboard displays is always the algorithm's actual output, not an
// authored number. Only the ground-truth position, a label, and a nominal
// weapon-class flavour string live here.

import type { FireTarget } from '../types';
import { nodeById } from './layout';
import { projectBearing } from '../geo';
import { nominalAccuracy } from './grid';

interface Def {
  id: string;
  label: string;
  node: string;
  azimuth: number;
  distance: number;
  weapon: string;
}

const DEFS: Def[] = [
  { id: 'DET-001', label: 'TREE LINE, EAST APPROACH', node: 'VAJRA-2', azimuth: 42.0, distance: 300.1, weapon: '5.56x45 RIFLE' },
  { id: 'DET-002', label: 'RIDGE NORTH OF AO', node: 'GARUD-1', azimuth: 305.4, distance: 512.8, weapon: '7.62x39 RIFLE' },
  { id: 'DET-003', label: 'OPEN GROUND, SOUTH FLANK', node: 'RUDRA-3', azimuth: 168.2, distance: 244.5, weapon: '5.56x45 RIFLE' },
  { id: 'DET-004', label: 'SCRUB BELT, WEST', node: 'VAJRA-1', azimuth: 251.7, distance: 388.9, weapon: 'UNCLASSIFIED' },
  { id: 'DET-005', label: 'TRACK JUNCTION, NE', node: 'GARUD-3', azimuth: 61.3, distance: 176.4, weapon: '5.56x45 RIFLE' },
  { id: 'DET-006', label: 'CANOPY EDGE, FAR NORTH', node: 'GARUD-2', azimuth: 349.6, distance: 623.0, weapon: 'UNCLASSIFIED' },
  { id: 'DET-007', label: 'CREEK BED, SE', node: 'RUDRA-1', azimuth: 118.5, distance: 205.2, weapon: '7.62x39 RIFLE' },
  { id: 'DET-008', label: 'STRUCTURE CLUSTER, W', node: 'VAJRA-3', azimuth: 279.9, distance: 341.6, weapon: '5.56x45 RIFLE' },
  { id: 'DET-009', label: 'TREE LINE, FAR EAST', node: 'GARUD-1', azimuth: 88.1, distance: 455.3, weapon: 'UNCLASSIFIED' },
  { id: 'DET-010', label: 'OPEN PLAIN, CENTRAL', node: 'RUDRA-2', azimuth: 22.7, distance: 288.0, weapon: '5.56x45 RIFLE' },
  { id: 'DET-011', label: 'RIDGE, SOUTH WEST', node: 'VAJRA-2', azimuth: 202.4, distance: 367.1, weapon: '7.62x39 RIFLE' },
  { id: 'DET-012', label: 'TRACK, NORTH APPROACH', node: 'GARUD-3', azimuth: 355.0, distance: 233.9, weapon: '5.56x45 RIFLE' },
];

export interface PresetTarget extends FireTarget {
  detecting_node: string;
}

export const PRESET_TARGETS: PresetTarget[] = DEFS.map((d) => {
  const node = nodeById(d.node)!;
  const pos = projectBearing(node.east, node.north, d.azimuth, d.distance);
  return {
    id: d.id,
    label: d.label,
    east: pos.east,
    north: pos.north,
    accuracy_pct: nominalAccuracy(d.distance),
    weapon_class: d.weapon,
    detecting_node: d.node,
  };
});
