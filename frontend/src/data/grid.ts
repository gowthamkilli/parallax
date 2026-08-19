// The manual-fire click surface: the AO is quantised into dense cells so a
// click always resolves to one well-defined ground-truth location. Each
// cell's accuracy_pct is a *nominal* prediction from sensor geometry (closer
// to a node net = louder = more confident) — it only seeds how noisy the
// simulated measurement fed to the backend is. It is intentionally never
// displayed: the only accuracy_pct shown anywhere in the UI is the real
// backend's, so there is one number, not two competing ones.

import { AO, toLatLon, compassBearing } from '../geo';
import { nearestNodes } from './layout';
import type { FireTarget } from '../types';

// Dense enough that clicking feels closer to continuous than blocky.
export const CELLS_PER_SIDE = 100;
export const CELL_SIZE = AO.extent_m / CELLS_PER_SIDE;

export interface GridCell extends FireTarget {
  col: number;
  row: number;
  latitude: number;
  longitude: number;
  direction: string;
  azimuth_deg: number;
  distance_m: number;
  nearestNode: string;
}

export function nominalAccuracy(distance_m: number): number {
  return Math.max(15, Math.min(96, 96 - distance_m * 0.09));
}

function buildGrid(): GridCell[] {
  const cells: GridCell[] = [];
  const half = AO.extent_m / 2;
  for (let row = 0; row < CELLS_PER_SIDE; row++) {
    for (let col = 0; col < CELLS_PER_SIDE; col++) {
      const east = -half + CELL_SIZE * (col + 0.5);
      const north = -half + CELL_SIZE * (row + 0.5);
      const [nearest] = nearestNodes(east, north, 1);
      const dx = east - nearest.east;
      const dy = north - nearest.north;
      const distance_m = Math.hypot(dx, dy);
      const azimuth_deg = (Math.atan2(dx, dy) * 180) / Math.PI;
      const az = ((azimuth_deg % 360) + 360) % 360;
      const { latitude, longitude } = toLatLon(east, north);
      cells.push({
        id: `GRID-${row}-${col}`,
        label: `MANUAL PLACEMENT — ${nearest.id} SECTOR`,
        col,
        row,
        east,
        north,
        latitude,
        longitude,
        direction: compassBearing(az),
        azimuth_deg: az,
        distance_m,
        nearestNode: nearest.id,
        accuracy_pct: nominalAccuracy(distance_m),
      });
    }
  }
  return cells;
}

export const GRID: GridCell[] = buildGrid();

export function cellAt(east: number, north: number): GridCell | null {
  const half = AO.extent_m / 2;
  const col = Math.floor((east + half) / CELL_SIZE);
  const row = Math.floor((north + half) / CELL_SIZE);
  if (col < 0 || col >= CELLS_PER_SIDE || row < 0 || row >= CELLS_PER_SIDE) return null;
  return GRID[row * CELLS_PER_SIDE + col];
}

/** Nominal-accuracy -> simulated per-node bearing noise sigma (degrees).
 *  Higher predicted accuracy => tighter simulated measurement => the real
 *  triangulation algorithm naturally resolves a tighter, more accurate fix.
 *  Kept modest at the low end so a click far from a node net still returns a
 *  usable (if less confident) fix rather than a wild outlier every time. */
export function accuracyToBearingSigmaDeg(accuracy_pct: number): number {
  return 0.4 + ((100 - accuracy_pct) / 100) * 6;
}

/** Faint reference lines only — no per-cell fill. A dense heatmap read as a
 *  graph-paper sheet and doubled as a second, frontend-only "accuracy"
 *  signal competing with the backend's real one. Just enough line weight to
 *  see the structure exists. */
export function bakeGridTexture(px = 1024): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = px;
  canvas.height = px;
  const ctx = canvas.getContext('2d')!;
  const cell = px / CELLS_PER_SIDE;

  ctx.strokeStyle = 'rgba(237,240,232,0.07)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= CELLS_PER_SIDE; i++) {
    const p = Math.round(i * cell) + 0.5;
    ctx.beginPath();
    ctx.moveTo(p, 0);
    ctx.lineTo(p, px);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, p);
    ctx.lineTo(px, p);
    ctx.stroke();
  }

  // Every 10th line a touch stronger so the eye can gauge scale without the
  // whole thing reading as a dense mesh.
  ctx.strokeStyle = 'rgba(237,240,232,0.14)';
  const major = 10;
  for (let i = 0; i <= CELLS_PER_SIDE; i += major) {
    const p = Math.round(i * cell) + 0.5;
    ctx.beginPath();
    ctx.moveTo(p, 0);
    ctx.lineTo(p, px);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, p);
    ctx.lineTo(px, p);
    ctx.stroke();
  }

  return canvas;
}
