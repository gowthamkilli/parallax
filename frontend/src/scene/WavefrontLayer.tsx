import { useEffect, useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html, Line } from '@react-three/drei';
import * as THREE from 'three';
import { useGdsStore } from '../store';
import { nodeById } from '../data/layout';
import { groundY } from './UnitsLayer';

const SPEED_OF_SOUND = 343; // m/s, real-time — farther nodes latch later, honestly
const FLASH_MS = 90;
const CONVERGE_MS = 500;
const BLOOM_MS = 500;

export default function WavefrontLayer() {
  const activeShot = useGdsStore((s) => s.activeShot);
  const advanceShotStage = useGdsStore((s) => s.advanceShotStage);
  const resolveShot = useGdsStore((s) => s.resolveShot);
  const clearActiveShot = useGdsStore((s) => s.clearActiveShot);
  const reducedMotion = useGdsStore((s) => s.reducedMotion);

  const ringRef = useRef<THREE.Mesh>(null);
  const [latches, setLatches] = useState<Record<string, number>>({});
  const stageTimers = useRef<{ convergedAt: number | null }>({ convergedAt: null });
  const resolvedRef = useRef(false);
  const bannerTimeout = useRef<number | null>(null);

  const contributing = useMemo(() => {
    if (!activeShot) return [];
    return (activeShot.shot.contributing_nodes ?? [activeShot.shot.detecting_node])
      .map((id) => nodeById(id))
      .filter(Boolean) as NonNullable<ReturnType<typeof nodeById>>[];
  }, [activeShot?.runId]);

  useEffect(() => {
    setLatches({});
    stageTimers.current.convergedAt = null;
    resolvedRef.current = false;
    if (bannerTimeout.current) window.clearTimeout(bannerTimeout.current);
    if (!activeShot) return;
    bannerTimeout.current = window.setTimeout(() => clearActiveShot(), reducedMotion ? 1200 : 5200);
    return () => {
      if (bannerTimeout.current) window.clearTimeout(bannerTimeout.current);
    };
  }, [activeShot?.runId]);

  useFrame(() => {
    if (!activeShot || !ringRef.current) return;
    const now = performance.now();
    const sinceStart = now - activeShot.firedAtMs;

    if (sinceStart < FLASH_MS) {
      ringRef.current.visible = false;
      return;
    }

    const wfElapsedS = reducedMotion ? 999 : (sinceStart - FLASH_MS) / 1000;
    const radius = Math.max(0.01, SPEED_OF_SOUND * wfElapsedS);
    ringRef.current.visible = activeShot.stage === 'flash' || activeShot.stage === 'wavefront';
    ringRef.current.scale.set(radius, radius, radius);
    const mat = ringRef.current.material as THREE.MeshBasicMaterial;
    mat.opacity = Math.max(0, 0.55 - radius / 900);

    if (activeShot.stage === 'flash') advanceShotStage('wavefront');

    let newLatchNode: string | null = null;
    for (const node of contributing) {
      if (latches[node.id] !== undefined) continue;
      const dist = Math.hypot(node.east - activeShot.targetEast, node.north - activeShot.targetNorth);
      if (radius >= dist) newLatchNode = node.id;
    }
    if (newLatchNode) {
      const dist = Math.hypot(
        nodeById(newLatchNode)!.east - activeShot.targetEast,
        nodeById(newLatchNode)!.north - activeShot.targetNorth
      );
      setLatches((prev) => ({ ...prev, [newLatchNode!]: dist / SPEED_OF_SOUND }));
    }

    const allLatched = contributing.length > 0 && contributing.every((n) => latches[n.id] !== undefined || n.id === newLatchNode);
    if (allLatched && activeShot.stage === 'wavefront') {
      advanceShotStage('converge');
      stageTimers.current.convergedAt = now;
    }

    if (activeShot.stage === 'converge' && stageTimers.current.convergedAt) {
      if (now - stageTimers.current.convergedAt > CONVERGE_MS + BLOOM_MS && !resolvedRef.current) {
        resolvedRef.current = true;
        resolveShot(sinceStart / 1000);
      }
    }
  });

  if (!activeShot) return null;

  const targetY = groundY(activeShot.targetEast, activeShot.targetNorth);
  const showConverge = activeShot.stage === 'converge' || activeShot.stage === 'resolved';
  const ellipseRadius = Math.max(2, 15 - (activeShot.shot.confidence_pct / 100) * 13);

  return (
    <group>
      {/* muzzle flash */}
      {activeShot.stage === 'flash' && (
        <mesh position={[activeShot.targetEast, targetY + 8, activeShot.targetNorth]}>
          <sphereGeometry args={[6, 12, 12]} />
          <meshBasicMaterial color="#fff2c0" transparent opacity={0.9} />
        </mesh>
      )}

      {/* expanding wavefront ring */}
      <mesh
        ref={ringRef}
        position={[activeShot.targetEast, targetY + 0.5, activeShot.targetNorth]}
        rotation={[-Math.PI / 2, 0, 0]}
        visible={false}
      >
        <ringGeometry args={[0.97, 1, 96]} />
        <meshBasicMaterial color="#edf0e8" transparent opacity={0.5} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>

      {/* node ping latches + timestamp chips */}
      {contributing.map((node) => {
        const latchT = latches[node.id];
        if (latchT === undefined) return null;
        return (
          <Html key={node.id} position={[node.east, groundY(node.east, node.north) + 10, node.north]} center zIndexRange={[25, 0]}>
            <div
              className="font-mono"
              style={{
                background: 'var(--panel)',
                border: '1px solid var(--friendly)',
                color: 'var(--friendly)',
                fontSize: 11,
                padding: '2px 6px',
                whiteSpace: 'nowrap',
              }}
            >
              {node.id} +{latchT.toFixed(3)}s
            </div>
          </Html>
        );
      })}

      {/* convergence hairlines */}
      {showConverge &&
        contributing.map((node) => (
          <Line
            key={node.id}
            points={[
              [node.east, groundY(node.east, node.north) + 1, node.north],
              [activeShot.targetEast, targetY + 1, activeShot.targetNorth],
            ]}
            color="#edf0e8"
            lineWidth={1}
            transparent
            opacity={0.75}
          />
        ))}

      {/* uncertainty ellipse bloom */}
      {showConverge && (
        <mesh position={[activeShot.targetEast, targetY + 0.6, activeShot.targetNorth]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[Math.max(0.5, ellipseRadius - 1.5), ellipseRadius, 48]} />
          <meshBasicMaterial color="#ffb627" transparent opacity={0.75} side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      )}
    </group>
  );
}
