// Procedural terrain fallback: layered value noise -> heightfield + baked
// landcover texture. No external assets, fully offline. If a real orthophoto
// is dropped into public/textures/terrain.jpg later, Terrain.tsx can be
// pointed at it instead with no change to the rest of the scene.

function hash(x: number, y: number, seed: number): number {
  let h = x * 374761393 + y * 668265263 + seed * 2147483647;
  h = (h ^ (h >>> 13)) * 1274126177;
  h = h ^ (h >>> 16);
  return ((h >>> 0) % 100000) / 100000;
}

function smooth(t: number): number {
  return t * t * (3 - 2 * t);
}

function valueNoise(x: number, y: number, seed: number): number {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const xf = x - xi;
  const yf = y - yi;
  const a = hash(xi, yi, seed);
  const b = hash(xi + 1, yi, seed);
  const c = hash(xi, yi + 1, seed);
  const d = hash(xi + 1, yi + 1, seed);
  const u = smooth(xf);
  const v = smooth(yf);
  return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v;
}

export function fbm(x: number, y: number, octaves = 5, seed = 1): number {
  let total = 0;
  let amp = 0.5;
  let freq = 1;
  let max = 0;
  for (let i = 0; i < octaves; i++) {
    total += valueNoise(x * freq, y * freq, seed + i * 17) * amp;
    max += amp;
    amp *= 0.5;
    freq *= 2;
  }
  return total / max;
}

export interface TrackPoint {
  x: number;
  y: number;
}

// A few dirt-track splines and a creek bed, authored as control points in
// [0,1] uv space so they scale with whatever extent the terrain uses.
export const TRACKS: TrackPoint[][] = [
  [
    { x: 0.02, y: 0.85 },
    { x: 0.22, y: 0.7 },
    { x: 0.4, y: 0.62 },
    { x: 0.55, y: 0.5 },
    { x: 0.68, y: 0.3 },
    { x: 0.9, y: 0.12 },
  ],
  [
    { x: 0.1, y: 0.15 },
    { x: 0.3, y: 0.28 },
    { x: 0.5, y: 0.34 },
    { x: 0.72, y: 0.48 },
    { x: 0.95, y: 0.55 },
  ],
];

export const CREEK: TrackPoint[] = [
  { x: 0.05, y: 0.35 },
  { x: 0.25, y: 0.42 },
  { x: 0.42, y: 0.4 },
  { x: 0.6, y: 0.55 },
  { x: 0.8, y: 0.68 },
  { x: 0.98, y: 0.72 },
];

export const CLEARINGS: { x: number; y: number; w: number; h: number }[] = [
  { x: 0.82, y: 0.85, w: 0.1, h: 0.08 },
  { x: 0.86, y: 0.8, w: 0.05, h: 0.04 },
];

function catmullRom(pts: TrackPoint[], t: number): TrackPoint {
  const n = pts.length - 1;
  const seg = Math.min(Math.floor(t * n), n - 1);
  const localT = t * n - seg;
  const p0 = pts[Math.max(seg - 1, 0)];
  const p1 = pts[seg];
  const p2 = pts[Math.min(seg + 1, n)];
  const p3 = pts[Math.min(seg + 2, n)];
  const t2 = localT * localT;
  const t3 = t2 * localT;
  const x =
    0.5 *
    (2 * p1.x +
      (-p0.x + p2.x) * localT +
      (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 +
      (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3);
  const y =
    0.5 *
    (2 * p1.y +
      (-p0.y + p2.y) * localT +
      (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 +
      (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t3);
  return { x, y };
}

function sampleSpline(pts: TrackPoint[], samples = 40): Float32Array {
  const out = new Float32Array((samples + 1) * 2);
  for (let i = 0; i <= samples; i++) {
    const p = catmullRom(pts, i / samples);
    out[i * 2] = p.x;
    out[i * 2 + 1] = p.y;
  }
  return out;
}

function distToPresampled(pts: Float32Array, u: number, v: number): number {
  let min = Infinity;
  for (let i = 0; i < pts.length; i += 2) {
    const dx = pts[i] - u;
    const dy = pts[i + 1] - v;
    const d = dx * dx + dy * dy;
    if (d < min) min = d;
  }
  return Math.sqrt(min);
}

// Splines sampled once at module load, not per pixel.
const TRACK_SAMPLES = TRACKS.map((t) => sampleSpline(t));
const CREEK_SAMPLES = sampleSpline(CREEK);

export type Landcover = 'canopy' | 'scrub' | 'open' | 'track' | 'water';

export function classify(u: number, v: number, seed = 7): { cover: Landcover; canopyMask: number } {
  const n = fbm(u * 4, v * 4, 5, seed);
  const detail = fbm(u * 18, v * 18, 3, seed + 99);
  const val = n * 0.75 + detail * 0.25;

  for (const track of TRACK_SAMPLES) {
    if (distToPresampled(track, u, v) < 0.008) return { cover: 'track', canopyMask: 0 };
  }
  if (distToPresampled(CREEK_SAMPLES, u, v) < 0.007) return { cover: 'water', canopyMask: 0 };
  for (const c of CLEARINGS) {
    if (u > c.x && u < c.x + c.w && v > c.y && v < c.y + c.h) return { cover: 'open', canopyMask: 0 };
  }

  if (val > 0.56) return { cover: 'canopy', canopyMask: Math.min(1, (val - 0.56) / 0.3) };
  if (val > 0.42) return { cover: 'scrub', canopyMask: 0 };
  return { cover: 'open', canopyMask: 0 };
}

export function heightAt(u: number, v: number, seed = 3): number {
  return fbm(u * 3, v * 3, 5, seed) * 40 - 20;
}

const COVER_COLOR: Record<Landcover, [number, number, number]> = {
  canopy: [0x2e, 0x3b, 0x22],
  scrub: [0x4a, 0x54, 0x33],
  open: [0x7c, 0x76, 0x54],
  track: [0x9c, 0x92, 0x76],
  water: [0x3a, 0x4a, 0x48],
};

export function bakeTerrainCanvas(size = 1024): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  const img = ctx.createImageData(size, size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const u = x / size;
      const v = y / size;
      const { cover } = classify(u, v);
      const [r, g, b] = COVER_COLOR[cover];
      const grain = (hash(x, y, 5) - 0.5) * 18;
      const hueShift = (fbm(u * 30, v * 30, 2, 21) - 0.5) * 10;
      const idx = (y * size + x) * 4;
      img.data[idx] = Math.max(0, Math.min(255, r + grain + hueShift));
      img.data[idx + 1] = Math.max(0, Math.min(255, g + grain + hueShift));
      img.data[idx + 2] = Math.max(0, Math.min(255, b + grain));
      img.data[idx + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}
