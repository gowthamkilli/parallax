import { create } from 'zustand';
import type { PresetShot, ResolvedContact, EventLogRow, TabId, ShotSource, FireTarget } from './types';
import { PRESET_TARGETS } from './data/presets';
import { projectBearing, parseCompassBearing, compassBearing, toLatLon } from './geo';
import { nodeById } from './data/layout';
import { playPing } from './lib/audio';
import { simulateNodeReports } from './lib/forwardSim';
import { solveNetwork } from './lib/backend';

export type ShotStage = 'idle' | 'flash' | 'wavefront' | 'converge' | 'resolved';

export interface ActiveShot {
  runId: string;
  shot: PresetShot;
  source: ShotSource;
  originEast: number;
  originNorth: number;
  /** Where the algorithm's reported fix projects to — the wavefront's
   *  convergence lines and the final marker land here. */
  targetEast: number;
  targetNorth: number;
  /** Where the shot actually happened — the muzzle flash, the expanding
   *  wavefront ring, and node-latch timing all originate here, since that's
   *  the physical event the sensors are detecting. Equal to targetEast/North
   *  when no ground truth is known (e.g. an external live feed). */
  truthEast: number;
  truthNorth: number;
  firedAtMs: number;
  stage: ShotStage;
  latched: string[]; // node ids that have latched the wavefront, in order
}

interface GdsState {
  presets: PresetShot[];
  tab: TabId;
  selectedPresetIdx: number;
  activeShot: ActiveShot | null;
  contacts: ResolvedContact[];
  eventLog: EventLogRow[];
  manualMode: boolean;
  devPanelOpen: boolean;
  reducedMotion: boolean;
  verificationIdx: number; // index into contacts, for tab 3 stepper
  audioEnabled: boolean;
  backendOnline: boolean | null; // null = not checked yet
  manualPending: boolean; // waiting on the backend for a manual-fire result

  loadPresets: (shots: PresetShot[]) => void;
  setTab: (t: TabId) => void;
  fireShot: (shot: PresetShot, source?: ShotSource) => void;
  fireGroundTruth: (target: FireTarget, source: ShotSource) => Promise<void>;
  fireManualAtCell: (target: FireTarget) => Promise<void>;
  firePresetAtIndex: (idx: number) => Promise<void>;
  setBackendOnline: (v: boolean) => void;
  advanceShotStage: (stage: ShotStage, latchedNode?: string) => void;
  resolveShot: (resolveTimeS: number) => void;
  clearActiveShot: () => void;
  setManualMode: (v: boolean) => void;
  toggleDevPanel: () => void;
  resetSession: () => void;
  setVerificationIdx: (i: number) => void;
  setAudioEnabled: (v: boolean) => void;
  setSelectedPresetIdx: (i: number) => void;
}

let runCounter = 0;

export const useGdsStore = create<GdsState>((set, get) => ({
  presets: [],
  tab: 1,
  selectedPresetIdx: 0,
  activeShot: null,
  contacts: [],
  eventLog: [],
  manualMode: false,
  devPanelOpen: false,
  reducedMotion:
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false,
  verificationIdx: -1,
  audioEnabled: true,
  backendOnline: null,
  manualPending: false,

  loadPresets: (shots) => set({ presets: shots }),

  setTab: (t) => set({ tab: t }),

  fireShot: (shot, source = 'preset') => {
    const node = nodeById(shot.detecting_node);
    const originEast = node ? node.east : 0;
    const originNorth = node ? node.north : 0;
    const target = projectBearing(originEast, originNorth, shot.azimuth_deg, shot.distance_m);
    const truthTarget = shot.truth
      ? projectBearing(originEast, originNorth, shot.truth.azimuth_deg, shot.truth.distance_m)
      : target;
    runCounter += 1;
    set({
      activeShot: {
        runId: `RUN-${runCounter}`,
        shot,
        source,
        originEast,
        originNorth,
        targetEast: target.east,
        targetNorth: target.north,
        truthEast: truthTarget.east,
        truthNorth: truthTarget.north,
        firedAtMs: performance.now(),
        stage: 'flash',
        latched: [],
      },
    });
  },

  // Shared by manual grid clicks AND the local preset library: simulate what
  // the sensor net would have measured for a ground-truth position, solve it
  // with the real backend algorithm, and fire whatever it returns. Nothing
  // displayed here is authored — the backend's output IS the reading, noise
  // and all. Falls back to a clearly-tagged client estimate only if the
  // backend is unreachable.
  fireGroundTruth: async (target, source) => {
    set({ manualPending: true });
    const { reports, contributing, sigmaDeg } = simulateNodeReports(target);
    const result = await solveNetwork(reports);
    set({ manualPending: false, backendOnline: result.reachable });

    const refNode = contributing[0];
    const dx = target.east - refNode.east;
    const dy = target.north - refNode.north;
    const trueDistance = Math.hypot(dx, dy);
    const trueAzimuth = (((Math.atan2(dx, dy) * 180) / Math.PI) % 360 + 360) % 360;
    const truth = { azimuth_deg: trueAzimuth, distance_m: trueDistance };

    const baseFields = {
      id: target.id,
      label: target.label,
      detecting_node: refNode.id,
      contributing_nodes: contributing.map((n) => n.id),
      snr_db: Math.max(4, 22 - sigmaDeg * 1.4),
      weapon_class: target.weapon_class ?? 'UNCLASSIFIED',
      truth,
    };

    const fix = result.ok ? result.fix : null;
    let shot: PresetShot;
    if (fix && fix.latitude !== null && fix.longitude !== null) {
      shot = {
        ...baseFields,
        direction: fix.direction,
        azimuth_deg: parseCompassBearing(fix.direction),
        distance_m: fix.range_m ?? trueDistance,
        latitude: fix.latitude,
        longitude: fix.longitude,
        confidence_pct: fix.accuracy_pct,
        algorithmSource: 'backend',
      };
    } else {
      // Backend unreachable or couldn't resolve a fix — fall back to a
      // clearly-tagged client-side estimate so the demo never dead-ends.
      const { latitude, longitude } = toLatLon(target.east, target.north);
      shot = {
        ...baseFields,
        direction: compassBearing(trueAzimuth),
        azimuth_deg: trueAzimuth,
        distance_m: trueDistance,
        latitude,
        longitude,
        confidence_pct: Math.max(10, target.accuracy_pct * 0.7),
        algorithmSource: 'client-fallback',
      };
    }
    get().fireShot(shot, source);
  },

  fireManualAtCell: (target) => get().fireGroundTruth(target, 'manual'),

  firePresetAtIndex: (idx) => {
    const target = PRESET_TARGETS[idx];
    if (!target) return Promise.resolve();
    return get().fireGroundTruth(target, 'preset');
  },

  setBackendOnline: (v) => set({ backendOnline: v }),

  advanceShotStage: (stage, latchedNode) =>
    set((s) => {
      if (!s.activeShot) return {};
      const latched = latchedNode
        ? [...new Set([...s.activeShot.latched, latchedNode])]
        : s.activeShot.latched;
      return { activeShot: { ...s.activeShot, stage, latched } };
    }),

  resolveShot: (resolveTimeS) =>
    set((s) => {
      const a = s.activeShot;
      if (!a) return {};
      const contact: ResolvedContact = {
        runId: a.runId,
        shot: a.shot,
        source: a.source,
        east: a.targetEast,
        north: a.targetNorth,
        truthEast: a.truthEast,
        truthNorth: a.truthNorth,
        resolveTimeS,
        firedAtMs: a.firedAtMs,
      };
      if (s.audioEnabled) playPing();
      const row: EventLogRow = {
        runId: a.runId,
        time: new Date().toLocaleTimeString('en-GB', { hour12: false }),
        bearing: a.shot.direction,
        range: `${a.shot.distance_m.toFixed(0)}m`,
        confidence: `${a.shot.confidence_pct.toFixed(0)}%`,
        nodes: (a.shot.contributing_nodes ?? [a.shot.detecting_node]).join(' '),
        source: a.source,
      };
      return {
        activeShot: { ...a, stage: 'resolved' },
        contacts: [...s.contacts, contact],
        eventLog: [row, ...s.eventLog].slice(0, 50),
        verificationIdx: s.contacts.length,
      };
    }),

  clearActiveShot: () => set({ activeShot: null }),
  setManualMode: (v) => set({ manualMode: v }),
  toggleDevPanel: () => set((s) => ({ devPanelOpen: !s.devPanelOpen })),
  resetSession: () => set({ contacts: [], eventLog: [], activeShot: null, verificationIdx: -1 }),
  setVerificationIdx: (i) => set({ verificationIdx: i }),
  setAudioEnabled: (v) => set({ audioEnabled: v }),
  setSelectedPresetIdx: (i) => set({ selectedPresetIdx: i }),
}));

// window.GDS bridge for backend integration — zero code changes required to
// swap presets.json for the real thing.
declare global {
  interface Window {
    GDS: {
      loadPresets: (shots: PresetShot[]) => void;
      feed: (shot: PresetShot) => void;
    };
  }
}

if (typeof window !== 'undefined') {
  window.GDS = {
    loadPresets: (shots) => useGdsStore.getState().loadPresets(shots),
    feed: (shot) => useGdsStore.getState().fireShot(shot, 'preset'),
  };
}
