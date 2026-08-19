import type { NodeReport } from './forwardSim';

const BASE_URL = 'http://127.0.0.1:8787';

export interface BackendFix {
  direction: string;
  range_m: number | null;
  latitude: number | null;
  longitude: number | null;
  accuracy_pct: number;
}

export type BackendResult =
  | { ok: true; reachable: true; fix: BackendFix }
  | { ok: false; reachable: true; error: string }
  | { ok: false; reachable: false; error: string };

export async function solveNetwork(reports: NodeReport[]): Promise<BackendResult> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}/api/network`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nodes: reports }),
      signal: AbortSignal.timeout(4000),
    });
  } catch (err) {
    return { ok: false, reachable: false, error: err instanceof Error ? err.message : 'network error' };
  }
  if (!res.ok) return { ok: false, reachable: true, error: `HTTP ${res.status}` };
  const json = await res.json();
  if (!json.ok) return { ok: false, reachable: true, error: json.error ?? 'unknown backend error' };
  return { ok: true, reachable: true, fix: json.fix };
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/api/health`, { signal: AbortSignal.timeout(1500) });
    return res.ok;
  } catch {
    return false;
  }
}

export { BASE_URL };
