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
  east: number;
  north: number;
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
