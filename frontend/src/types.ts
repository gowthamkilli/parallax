// GDS data contract. This is the only shape that crosses the backend boundary.
// Everything except `truth` is produced by the backend; the front end renders it.

export interface PresetShot {
  id: string;
  label: string;
  t_offset_ms?: number;

  direction: string;
  azimuth_deg: number;
  distance_m: number;
  latitude: number;
  longitude: number;
  confidence_pct: number;
  detecting_node: string;
  contributing_nodes?: string[];
  tdoa_ms?: number[];
  snr_db?: number;
  weapon_class?: string;

  truth?: { azimuth_deg: number; distance_m: number };

  /** Manual-fire only: whether the localisation came from the real backend
   *  algorithm or a client-side fallback estimate (backend unreachable). */
  algorithmSource?: 'backend' | 'client-fallback';
}

export type NodeId = string;

export interface SensorNode {
  id: NodeId;
  unit: string;
  /** ENU metres, relative to AO anchor */
  east: number;
  north: number;
  /** array heading, degrees true, for the polar rosette */
  heading_deg: number;
  online: boolean;
}

export interface Personnel {
  id: string;
  unit: string;
  east: number;
  north: number;
  isNodeCarrier: boolean;
}

export interface Unit {
  id: string;
  callsign: string;
  personnelCount: number;
  centerEast: number;
  centerNorth: number;
  radius: number;
  rssi_dbm: number;
  power_pct: number;
  linkStatus: string;
}

export type ShotSource = 'preset' | 'manual';

export interface ResolvedContact {
  runId: string;
  shot: PresetShot;
  source: ShotSource;
  /** Where the algorithm's reported fix projects to on the map. */
  east: number;
  north: number;
  /** Where the shot actually happened (ground truth), when known — same as
   *  east/north when no truth is available (e.g. an external live feed). The
   *  gap between the two IS the algorithm's real, computed detection error;
   *  showing both instead of only the reported point is what makes that
   *  error legible instead of looking like a misplaced click. */
  truthEast: number;
  truthNorth: number;
  resolveTimeS: number;
  firedAtMs: number;
}

export interface EventLogRow {
  runId: string;
  time: string;
  bearing: string;
  range: string;
  confidence: string;
  nodes: string;
  source: ShotSource;
}

export type TabId = 1 | 2 | 3;

/** Minimal shape needed to forward-simulate sensor readings and fire them
 *  through the real backend algorithm. GridCell and preset ground-truth
 *  targets both satisfy this — one pipeline (store.fireGroundTruth) drives
 *  both, so every reading shown by the dashboard, preset or manual, is
 *  actually computed by parallax.localize rather than hand-authored. */
export interface FireTarget {
  id: string;
  label: string;
  east: number;
  north: number;
  accuracy_pct: number;
  weapon_class?: string;
}
