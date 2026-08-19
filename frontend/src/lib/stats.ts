import type { ResolvedContact } from '../types';

function angDelta(a: number, b: number): number {
  let d = a - b;
  while (d > 180) d -= 360;
  while (d < -180) d += 360;
  return d;
}

export interface SessionStats {
  count: number;
  meanConfidence: number;
  meanResolveTime: number;
  bearingMin: number;
  bearingMax: number;
  hasTruth: boolean;
  meanBearingError?: number;
  meanRangeErrorPct?: number;
  cep50?: number;
}

export function computeSessionStats(contacts: ResolvedContact[]): SessionStats {
  const preset = contacts.filter((c) => c.source === 'preset');
  if (preset.length === 0) {
    return { count: 0, meanConfidence: 0, meanResolveTime: 0, bearingMin: 0, bearingMax: 0, hasTruth: false };
  }
  const confidences = preset.map((c) => c.shot.confidence_pct);
  const resolveTimes = preset.map((c) => c.resolveTimeS);
  const bearings = preset.map((c) => c.shot.azimuth_deg);

  const withTruth = preset.filter((c) => c.shot.truth);
  let meanBearingError: number | undefined;
  let meanRangeErrorPct: number | undefined;
  let cep50: number | undefined;

  if (withTruth.length === preset.length && withTruth.length > 0) {
    const bearingErrors = withTruth.map((c) => Math.abs(angDelta(c.shot.azimuth_deg, c.shot.truth!.azimuth_deg)));
    const rangeErrors = withTruth.map(
      (c) => (Math.abs(c.shot.distance_m - c.shot.truth!.distance_m) / c.shot.truth!.distance_m) * 100
    );
    const posErrors = withTruth.map((c) => Math.hypot(c.truthEast - c.east, c.truthNorth - c.north));
    meanBearingError = bearingErrors.reduce((a, b) => a + b, 0) / bearingErrors.length;
    meanRangeErrorPct = rangeErrors.reduce((a, b) => a + b, 0) / rangeErrors.length;
    const sorted = [...posErrors].sort((a, b) => a - b);
    cep50 = sorted[Math.floor(sorted.length / 2)];
  }

  return {
    count: preset.length,
    meanConfidence: confidences.reduce((a, b) => a + b, 0) / confidences.length,
    meanResolveTime: resolveTimes.reduce((a, b) => a + b, 0) / resolveTimes.length,
    bearingMin: Math.min(...bearings),
    bearingMax: Math.max(...bearings),
    hasTruth: withTruth.length === preset.length && withTruth.length > 0,
    meanBearingError,
    meanRangeErrorPct,
    cep50,
  };
}
