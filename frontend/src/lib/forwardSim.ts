// Forward model for manual-fire: turns a ground-truth grid cell into the
// per-node bearing measurements the real acoustic nodes would have reported,
// so the click can be fed through the actual parallax.localize triangulation
// algorithm instead of being faked client-side. Bearing-only observations
// (no crack-thump fields) are deliberately omitted -- the backend then falls
// back to cross-bearing triangulation across nodes, which is exactly the
// "several teams report the same shot" path parallax.localize_network exists
// for.

import { accuracyToBearingSigmaDeg } from '../data/grid';
import { nearestNodes } from '../data/layout';
import type { FireTarget, SensorNode } from '../types';
import { toLatLon } from '../geo';

export interface NodeReport {
  node: { id: string; lat: number; lon: number };
  measurement: { blast_bearing_deg: number };
}

function gaussian(sigma: number): number {
  // Box-Muller
  const u1 = Math.max(1e-9, Math.random());
  const u2 = Math.random();
  return sigma * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

export interface ForwardSimResult {
  reports: NodeReport[];
  contributing: SensorNode[];
  sigmaDeg: number;
}

export function simulateNodeReports(target: FireTarget, nodeCount = 3): ForwardSimResult {
  const contributing = nearestNodes(target.east, target.north, nodeCount);
  const sigmaDeg = accuracyToBearingSigmaDeg(target.accuracy_pct);

  const reports: NodeReport[] = contributing.map((node) => {
    const dx = target.east - node.east;
    const dy = target.north - node.north;
    const trueBearing = (Math.atan2(dx, dy) * 180) / Math.PI;
    const measured = ((trueBearing + gaussian(sigmaDeg)) % 360 + 360) % 360;
    const { latitude, longitude } = nodeLatLon(node);
    return {
      node: { id: node.id, lat: latitude, lon: longitude },
      measurement: { blast_bearing_deg: measured },
    };
  });

  return { reports, contributing, sigmaDeg };
}

// Nodes are stored in local ENU metres; the backend wants lat/lon.
function nodeLatLon(node: SensorNode): { latitude: number; longitude: number } {
  return toLatLon(node.east, node.north);
}
