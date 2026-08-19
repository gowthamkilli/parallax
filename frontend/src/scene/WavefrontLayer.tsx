import { useEffect, useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { useGdsStore } from '../store';
import { nodeById } from '../data/layout';
import type { SensorNode } from '../types';
import { groundY } from './UnitsLayer';

const SPEED_OF_SOUND = 343; // m/s, real-time — farther nodes latch later, honestly
const FLASH_MS = 90;
const CONVERGE_MS = 500;
const BLOOM_MS = 500;
const ECHO_PHASES_S = [0, 0.16, 0.32]; // trailing ripple rings behind the leading edge
const CONNECT_STAGGER_MS = 110; // each team's report converges slightly after the last
const CONNECT_DRAW_MS = 420;
const PING_MS = 650;

function easeOutCubic(t: number): number {
  const c = Math.min(1, Math.max(0, t));
  return 1 - Math.pow(1 - c, 3);
}

interface ConnectAssets {
  pulseRef: THREE.Mesh | null;
}

// This component drives its own animation entirely inside useFrame, and it
// also calls advanceShotStage/resolveShot on the store — which replace
// activeShot with a new object on every stage transition. Subscribing to the
// full activeShot reactively would re-render this component 3+ times during
// one ~2.4s shot, and each re-render re-applies the JSX's literal initial
// props (visible={false}, opacity={0}, a fresh Float32Array), stomping
// whatever the imperative frame loop had just set. So: subscribe only to the
// stable runId for structure, and read live stage/position data imperatively
// via getState() inside useFrame, never through a reactive selector.
export default function WavefrontLayer() {
  const runId = useGdsStore((s) => s.activeShot?.runId);
  const advanceShotStage = useGdsStore((s) => s.advanceShotStage);
  const resolveShot = useGdsStore((s) => s.resolveShot);
  const clearActiveShot = useGdsStore((s) => s.clearActiveShot);
  const reducedMotion = useGdsStore((s) => s.reducedMotion);

  const ringRefs = useRef<(THREE.Mesh | null)[]>([]);
  const flashRef = useRef<THREE.Mesh>(null);
  const ellipseRef = useRef<THREE.Mesh>(null);
  const highlightRef = useRef<THREE.Mesh>(null);
  const pingRefs = useRef<Record<string, THREE.Mesh | null>>({});
  const connectAssets = useRef<Record<string, ConnectAssets>>({});
  const latchesRef = useRef<Record<string, number>>({});
  const convergedAtRef = useRef<number | null>(null);
  const resolvedRef = useRef(false);
  const bannerTimeout = useRef<number | null>(null);

  // Snapshot taken once per new shot — the shot/target/contributing-node set
  // never changes mid-animation, so this is safe to freeze at mount.
  const shotSnapshot = useMemo(() => {
    if (!runId) return null;
    const activeShot = useGdsStore.getState().activeShot;
    if (!activeShot || activeShot.runId !== runId) return null;
    const contributing = (activeShot.shot.contributing_nodes ?? [activeShot.shot.detecting_node])
      .map((id) => nodeById(id))
      .filter(Boolean) as NonNullable<ReturnType<typeof nodeById>>[];
    return { activeShot, contributing };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const contributing = shotSnapshot?.contributing ?? [];

  useEffect(() => {
    latchesRef.current = {};
    convergedAtRef.current = null;
    resolvedRef.current = false;
    connectAssets.current = {};
    for (const node of contributing) connectAssets.current[node.id] = { pulseRef: null };
    if (bannerTimeout.current) window.clearTimeout(bannerTimeout.current);
    if (!runId) return;
    bannerTimeout.current = window.setTimeout(() => clearActiveShot(), reducedMotion ? 1200 : 5200);
    return () => {
      if (bannerTimeout.current) window.clearTimeout(bannerTimeout.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, clearActiveShot, reducedMotion]);

  useFrame(() => {
    if (!shotSnapshot) return;
    const { activeShot } = shotSnapshot;
    // Live stage, read fresh every frame — never through the reactive hook.
    const live = useGdsStore.getState().activeShot;
    if (!live || live.runId !== activeShot.runId) return;
    const stage = live.stage;
    const latches = latchesRef.current;

    const now = performance.now();
    const sinceStart = now - activeShot.firedAtMs;
    const targetY = groundY(activeShot.targetEast, activeShot.targetNorth);

    // muzzle flash: quick bloom-and-fade instead of a static sphere
    if (flashRef.current) {
      if (sinceStart < FLASH_MS) {
        const t = sinceStart / FLASH_MS;
        flashRef.current.visible = true;
        const s = 1 + t * 5;
        flashRef.current.scale.set(s, s, s);
        (flashRef.current.material as THREE.MeshBasicMaterial).opacity = 1 - t;
      } else {
        flashRef.current.visible = false;
      }
    }

    if (sinceStart < FLASH_MS) {
      ringRefs.current.forEach((r) => r && (r.visible = false));
      return;
    }

    const wfElapsedS = reducedMotion ? 999 : (sinceStart - FLASH_MS) / 1000;
    const leadRadius = Math.max(0.01, SPEED_OF_SOUND * wfElapsedS);
    const wavefrontLive = stage === 'flash' || stage === 'wavefront';

    ECHO_PHASES_S.forEach((phase, i) => {
      const ring = ringRefs.current[i];
      if (!ring) return;
      const r = SPEED_OF_SOUND * Math.max(0, wfElapsedS - phase);
      const visible = wavefrontLive && r > 0.01;
      ring.visible = visible;
      if (visible) {
        ring.scale.set(r, r, r);
        const mat = ring.material as THREE.MeshBasicMaterial;
        mat.opacity = Math.max(0, (0.55 - i * 0.15) - r / 900);
      }
    });

    if (stage === 'flash') advanceShotStage('wavefront');

    let newLatchNode: string | null = null;
    for (const node of contributing) {
      if (latches[node.id] !== undefined) continue;
      // Physical propagation is from the true shot location, not wherever
      // the algorithm eventually concludes it was.
      const dist = Math.hypot(node.east - activeShot.truthEast, node.north - activeShot.truthNorth);
      if (leadRadius >= dist) newLatchNode = node.id;
    }
    if (newLatchNode) {
      const dist = Math.hypot(
        nodeById(newLatchNode)!.east - activeShot.truthEast,
        nodeById(newLatchNode)!.north - activeShot.truthNorth
      );
      latches[newLatchNode] = dist / SPEED_OF_SOUND;
    }

    const allLatched = contributing.length > 0 && contributing.every((n) => latches[n.id] !== undefined);
    if (allLatched && stage === 'wavefront') {
      advanceShotStage('converge');
      convergedAtRef.current = now;
    }

    // local ping ripple at each node the instant it latches
    contributing.forEach((node) => {
      const latchT = latches[node.id];
      const ping = pingRefs.current[node.id];
      if (!ping || latchT === undefined) return;
      const latchAbsMs = activeShot.firedAtMs + FLASH_MS + latchT * 1000;
      const localT = (now - latchAbsMs) / PING_MS;
      if (localT < 0 || localT > 1) {
        ping.visible = false;
        return;
      }
      ping.visible = true;
      const s = 1 + easeOutCubic(localT) * 9;
      ping.scale.set(s, s, s);
      (ping.material as THREE.MeshBasicMaterial).opacity = (1 - localT) * 0.8;
    });

    // convergence: each team's report travels to the fix as a moving glow —
    // no drawn line, just motion, so multiple teams "arriving" at an answer
    // reads from movement rather than a static diagram.
    const convergedAt = convergedAtRef.current;
    if (convergedAt !== null && (stage === 'converge' || stage === 'resolved')) {
      contributing.forEach((node, i) => {
        const assets = connectAssets.current[node.id];
        if (!assets?.pulseRef) return;
        const elapsed = now - convergedAt - i * CONNECT_STAGGER_MS;
        const progress = easeOutCubic(elapsed / CONNECT_DRAW_MS);
        const drawing = elapsed > 0;

        const nodeY = groundY(node.east, node.north) + 1;
        const ex = node.east + (activeShot.targetEast - node.east) * progress;
        const ey = nodeY + (targetY + 1 - nodeY) * progress;
        const ez = node.north + (activeShot.targetNorth - node.north) * progress;

        assets.pulseRef.visible = drawing && progress < 1;
        assets.pulseRef.position.set(ex, ey, ez);
      });
    }

    // highlight at the true shot location — breathes gently for the whole
    // animation, then fades once the fix has resolved, so the click point
    // itself stays legible without ever drawing a line to it.
    if (highlightRef.current) {
      if (stage === 'resolved') {
        const fadeT = Math.min(1, (now - (convergedAt ?? now) - CONVERGE_MS - BLOOM_MS) / 900);
        (highlightRef.current.material as THREE.MeshBasicMaterial).opacity = Math.max(0, 0.5 * (1 - fadeT));
      } else {
        const pulse = 0.4 + Math.sin(sinceStart / 220) * 0.15;
        (highlightRef.current.material as THREE.MeshBasicMaterial).opacity = pulse;
      }
      const breathe = 1 + Math.sin(sinceStart / 220) * 0.08;
      highlightRef.current.scale.set(breathe, breathe, breathe);
    }

    if (stage === 'converge' && convergedAt) {
      if (now - convergedAt > CONVERGE_MS + BLOOM_MS && !resolvedRef.current) {
        resolvedRef.current = true;
        resolveShot(sinceStart / 1000);
      }
    }

    // uncertainty ellipse: elastic bloom-in rather than an instant pop
    if (ellipseRef.current && convergedAt) {
      const bloomT = Math.min(1, (now - convergedAt - CONVERGE_MS * 0.6) / BLOOM_MS);
      const visible = bloomT > 0;
      ellipseRef.current.visible = visible;
      if (visible) {
        const overshoot = 1 + Math.sin(Math.min(1, bloomT) * Math.PI) * 0.15 * (1 - bloomT);
        const s = easeOutCubic(bloomT) * overshoot;
        ellipseRef.current.scale.set(Math.max(0.01, s), Math.max(0.01, s), 1);
      }
    }
  });

  if (!shotSnapshot) return null;
  const { activeShot } = shotSnapshot;

  const targetY = groundY(activeShot.targetEast, activeShot.targetNorth);
  const truthY = groundY(activeShot.truthEast, activeShot.truthNorth);
  const ellipseRadius = Math.max(2, 15 - (activeShot.shot.confidence_pct / 100) * 13);

  return (
    <group>
      {/* highlight at the click / true shot location — breathes for the
          whole animation, no line, so the point itself stays legible */}
      <mesh
        ref={highlightRef}
        position={[activeShot.truthEast, truthY + 0.7, activeShot.truthNorth]}
        rotation={[-Math.PI / 2, 0, 0]}
      >
        <ringGeometry args={[5, 6.5, 32]} />
        <meshBasicMaterial color="#7fe3b0" transparent opacity={0.4} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>

      {/* muzzle flash — at the true shot location; the physical event, not
          the algorithm's eventual (possibly offset) conclusion */}
      <mesh ref={flashRef} position={[activeShot.truthEast, truthY + 8, activeShot.truthNorth]} visible={false}>
        <sphereGeometry args={[5, 12, 12]} />
        <meshBasicMaterial color="#fff2c0" transparent opacity={0.9} depthWrite={false} />
      </mesh>

      {/* expanding wavefront — leading edge + two trailing echoes, also at
          the true origin: this is the acoustic event physically propagating */}
      {ECHO_PHASES_S.map((_, i) => (
        <mesh
          key={i}
          ref={(el) => {
            ringRefs.current[i] = el;
          }}
          position={[activeShot.truthEast, truthY + 0.5, activeShot.truthNorth]}
          rotation={[-Math.PI / 2, 0, 0]}
          visible={false}
        >
          <ringGeometry args={[0.97, 1, 96]} />
          <meshBasicMaterial color="#edf0e8" transparent opacity={0.5} side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      ))}

      {/* per-node local ping ripple, fires the instant that node latches */}
      {contributing.map((node) => (
        <mesh
          key={`ping-${node.id}`}
          ref={(el) => {
            pingRefs.current[node.id] = el;
          }}
          position={[node.east, groundY(node.east, node.north) + 0.6, node.north]}
          rotation={[-Math.PI / 2, 0, 0]}
          visible={false}
        >
          <ringGeometry args={[0.8, 1, 32]} />
          <meshBasicMaterial color="#7fe3b0" transparent opacity={0} side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      ))}

      {/* node ping latches + timestamp chips */}
      {contributing.map((node) => (
        <LatchChip key={node.id} node={node} latchesRef={latchesRef} />
      ))}

      {/* convergence: each team's report travels to the fix as a moving
          glow — motion instead of a drawn line */}
      {contributing.map((node) => (
        <mesh
          key={`connect-${node.id}`}
          ref={(el) => {
            if (connectAssets.current[node.id]) connectAssets.current[node.id].pulseRef = el;
          }}
          visible={false}
        >
          <sphereGeometry args={[2.2, 10, 10]} />
          <meshBasicMaterial color="#7fe3b0" transparent opacity={0.95} depthWrite={false} />
        </mesh>
      ))}

      {/* uncertainty ellipse bloom */}
      <mesh
        ref={ellipseRef}
        position={[activeShot.targetEast, targetY + 0.6, activeShot.targetNorth]}
        rotation={[-Math.PI / 2, 0, 0]}
        visible={false}
      >
        <ringGeometry args={[Math.max(0.5, ellipseRadius - 1.5), ellipseRadius, 48]} />
        <meshBasicMaterial color="#ffb627" transparent opacity={0.75} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
    </group>
  );
}

// Isolated so its re-renders (triggered by polling the shared latchesRef)
// never touch WavefrontLayer's other, purely-imperative children.
function LatchChip({ node, latchesRef }: { node: SensorNode; latchesRef: React.RefObject<Record<string, number>> }) {
  const [latchT, setLatchT] = useState<number | undefined>(undefined);

  useFrame(() => {
    const current = latchesRef.current[node.id];
    if (current !== undefined && current !== latchT) setLatchT(current);
  });

  if (latchT === undefined) return null;

  return (
    <Html position={[node.east, groundY(node.east, node.north) + 10, node.north]} center zIndexRange={[25, 0]}>
      <div
        className="font-mono"
        style={{
          background: 'var(--panel)',
          border: '1px solid var(--friendly)',
          color: 'var(--friendly)',
          fontSize: 11,
          padding: '2px 6px',
          whiteSpace: 'nowrap',
          fontWeight: 700,
        }}
      >
        {node.id} +{latchT.toFixed(3)}s
      </div>
    </Html>
  );
}
