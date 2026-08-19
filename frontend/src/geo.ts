// Local ENU metric frame <-> geodetic conversion. One anchor constant; relocating
// the whole demo to a different AO is a one-line change and no displayed value
// can ever contradict another, since every panel derives from the same math.

export const AO = {
  anchor_lat: 28.616949,
  anchor_lon: 77.211075,
  designator: 'AO GRID 43R-FQ',
  label: 'MIXED FOREST / OPEN PLAIN',
  extent_m: 2500,
};

const M_PER_DEG_LAT = 111320;

export function toEastNorth(lat: number, lon: number): { east: number; north: number } {
  const north = (lat - AO.anchor_lat) * M_PER_DEG_LAT;
  const east = (lon - AO.anchor_lon) * M_PER_DEG_LAT * Math.cos((AO.anchor_lat * Math.PI) / 180);
  return { east, north };
}

export function toLatLon(east: number, north: number): { latitude: number; longitude: number } {
  const latitude = AO.anchor_lat + north / M_PER_DEG_LAT;
  const longitude =
    AO.anchor_lon + east / (M_PER_DEG_LAT * Math.cos((AO.anchor_lat * Math.PI) / 180));
  return { latitude, longitude };
}

/** Project a bearing (deg true, N=0, cw) + range (m) from an origin into ENU metres. */
export function projectBearing(
  originEast: number,
  originNorth: number,
  azimuthDeg: number,
  rangeM: number
): { east: number; north: number } {
  const rad = (azimuthDeg * Math.PI) / 180;
  return {
    east: originEast + Math.sin(rad) * rangeM,
    north: originNorth + Math.cos(rad) * rangeM,
  };
}

/** Quadrant compass bearing e.g. "N42.0E" -> true azimuth degrees. Fallback parser
 *  for when the backend cannot emit azimuth_deg directly. */
export function parseCompassBearing(direction: string): number {
  const s = direction.trim().toUpperCase();
  if (s === 'N') return 0;
  if (s === 'E') return 90;
  if (s === 'S') return 180;
  if (s === 'W') return 270;
  const m = s.match(/^([NS])(\d+(?:\.\d+)?)([EW])$/);
  if (!m) return 0;
  const [, ns, deg, ew] = m;
  const d = parseFloat(deg);
  if (ns === 'N' && ew === 'E') return d;
  if (ns === 'S' && ew === 'E') return 180 - d;
  if (ns === 'S' && ew === 'W') return 180 + d;
  return 360 - d; // N..W
}

export function compassBearing(azimuthDeg: number): string {
  const a = ((azimuthDeg % 360) + 360) % 360;
  if (a === 0) return 'N';
  if (a === 90) return 'E';
  if (a === 180) return 'S';
  if (a === 270) return 'W';
  if (a < 90) return `N${a.toFixed(1)}E`;
  if (a < 180) return `S${(180 - a).toFixed(1)}E`;
  if (a < 270) return `S${(a - 180).toFixed(1)}W`;
  return `N${(360 - a).toFixed(1)}W`;
}

export const metresToWorld = (m: number) => m / 1; // 1 world unit = 1 metre
