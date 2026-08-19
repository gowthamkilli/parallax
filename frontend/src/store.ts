import { create } from 'zustand';
import type { PresetShot, ResolvedContact, EventLogRow, TabId, ShotSource } from './types';
import { PRESETS } from './data/presets';
import { AO, projectBearing, compassBearing } from './geo';
import { nodeById, nearestNodes } from './data/layout';
import { playPing } from './lib/audio';

export type ShotStage = 'idle' | 'flash' | 'wavefront' | 'converge' | 'resolved';

export interface ActiveShot {
  runId: string;
  shot: PresetShot;
  source: ShotSource;
  originEast: number;
  originNorth: number;
  targetEast: number;
  targetNorth: number;
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

  loadPresets: (shots: PresetShot[]) => void;
  setTab: (t: TabId) => void;
  fireShot: (shot: PresetShot, source?: ShotSource) => void;
  fireManual: (east: number, north: number) => void;
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
  presets: PRESETS,
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

  loadPresets: (shots) => set({ presets: shots }),

  setTab: (t) => set({ tab: t }),

  fireShot: (shot, source = 'preset') => {
    const node = nodeById(shot.detecting_node);
    const originEast = node ? node.east : 0;
    const originNorth = node ? node.north : 0;
    const target = projectBearing(originEast, originNorth, shot.azimuth_deg, shot.distance_m);
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
        firedAtMs: performance.now(),
        stage: 'flash',
        latched: [],
      },
    });
  },

  fireManual: (east, north) => {
    const nearest = nearestNodes(east, north, 3);
    const ref = nearest[0];
    const dx = east - ref.east;
    const dy = north - ref.north;
    const distance_m = Math.sqrt(dx * dx + dy * dy);
    const azimuth_deg = (Math.atan2(dx, dy) * 180) / Math.PI;
    const az = ((azimuth_deg % 360) + 360) % 360;
    const M = 111320;
    const latitude = AO.anchor_lat + north / M;
    const longitude = AO.anchor_lon + east / (M * Math.cos((AO.anchor_lat * Math.PI) / 180));
    const shot: PresetShot = {
      id: `SIM-${runCounter + 1}`,
      label: 'MANUAL PLACEMENT',
      direction: compassBearing(az),
      azimuth_deg: az,
      distance_m,
      latitude,
      longitude,
      confidence_pct: 62 + Math.random() * 20,
      detecting_node: ref.id,
      contributing_nodes: nearest.map((n) => n.id),
      snr_db: 8 + Math.random() * 10,
      weapon_class: 'UNCLASSIFIED',
    };
    get().fireShot(shot, 'manual');
  },

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
