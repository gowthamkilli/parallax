import { useEffect, useMemo, useRef, useState } from 'react';
import { Html, Line } from '@react-three/drei';
import * as THREE from 'three';
import gsap from 'gsap';
import { useGdsStore } from '../store';
import { nodeById } from '../data/layout';
import { groundY } from './UnitsLayer';
import { EXTENT } from './Terrain';

function arcPoints(centerE: number, centerN: number, y: number, fromDeg: number, toDeg: number, radius: number, progress: number): [number, number, number][] {
  let delta = toDeg - fromDeg;
  while (delta > 180) delta -= 360;
  while (delta < -180) delta += 360;
  const endDeg = fromDeg + delta * progress;
  const steps = 32;
  const pts: [number, number, number][] = [];
  const lo = Math.min(fromDeg, endDeg);
  const hi = Math.max(fromDeg, endDeg);
  for (let i = 0; i <= steps; i++) {
    const a = ((lo + ((hi - lo) * i) / steps) * Math.PI) / 180;
    pts.push([centerE + Math.sin(a) * radius, y, centerN + Math.cos(a) * radius]);
  }
  return pts;
}

function wedgeGeometry(fromDeg: number, toDeg: number, radius: number): THREE.ShapeGeometry {
  let delta = toDeg - fromDeg;
  while (delta > 180) delta -= 360;
  while (delta < -180) delta += 360;
  const shape = new THREE.Shape();
  shape.moveTo(0, 0);
  const steps = 24;
  for (let i = 0; i <= steps; i++) {
    const a = ((fromDeg + (delta * i) / steps) * Math.PI) / 180;
    const x = Math.sin(a) * radius;
    const y = Math.cos(a) * radius;
    if (i === 0) shape.lineTo(x, y);
    else shape.lineTo(x, y);
  }
  shape.lineTo(0, 0);
  return new THREE.ShapeGeometry(shape);
}

export default function VerificationOverlay() {
  const tab = useGdsStore((s) => s.tab);
  const contacts = useGdsStore((s) => s.contacts);
  const verificationIdx = useGdsStore((s) => s.verificationIdx);
  const reducedMotion = useGdsStore((s) => s.reducedMotion);
  const [progress, setProgress] = useState({ grid: 0, reticle: 0, measure: 0, bearing: 0 });
  const proxy = useRef({ grid: 0, reticle: 0, measure: 0, bearing: 0 });

  const active = tab === 3 && verificationIdx >= 0 && verificationIdx < contacts.length;
  const contact = active ? contacts[verificationIdx] : null;

  useEffect(() => {
    if (!active) {
      proxy.current = { grid: 0, reticle: 0, measure: 0, bearing: 0 };
      setProgress({ grid: 0, reticle: 0, measure: 0, bearing: 0 });
      return;
    }
    const tl = gsap.timeline({
      onUpdate: () => setProgress({ ...proxy.current }),
    });
    if (reducedMotion) {
      proxy.current = { grid: 1, reticle: 1, measure: 1, bearing: 1 };
      setProgress({ ...proxy.current });
      return;
    }
    tl.to(proxy.current, { grid: 1, duration: 0.6, ease: 'power1.out' })
      .to(proxy.current, { reticle: 1, duration: 0.6, ease: 'power2.out' }, 0.3)
      .to(proxy.current, { measure: 1, duration: 0.6, ease: 'power2.out' }, 0.75)
      .to(proxy.current, { bearing: 1, duration: 0.6, ease: 'power2.out' }, 1.15);
    return () => {
      tl.kill();
    };
  }, [active, contact?.runId, reducedMotion]);

  const grid = useMemo(() => {
    const g = new THREE.GridHelper(EXTENT, 25, '#4a7fb5', '#4a7fb5');
    const mat = g.material as THREE.LineBasicMaterial;
    mat.transparent = true;
    return g;
  }, []);

  if (!active || !contact) return null;

  const node = nodeById(contact.shot.detecting_node);
  if (!node) return null;
  const nodeY = groundY(node.east, node.north) + 1;
  const targetY = groundY(contact.east, contact.north) + 1;
  const midE = (node.east + contact.east) / 2;
  const midN = (node.north + contact.north) / 2;
  const truth = contact.shot.truth;

  (grid.material as THREE.LineBasicMaterial).opacity = 0.28 * progress.grid;

  return (
    <group>
      <primitive object={grid} position={[0, 0.3, 0]} />

      {/* reticles */}
      <group position={[node.east, nodeY, node.north]} scale={progress.reticle}>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[6, 7, 4]} />
          <meshBasicMaterial color="#ff3b30" />
        </mesh>
      </group>
      <group position={[contact.east, targetY, contact.north]} scale={progress.reticle}>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[6, 7, 4]} />
          <meshBasicMaterial color="#ff3b30" />
        </mesh>
      </group>

      {/* measurement line */}
      {progress.measure > 0.01 && (
        <Line
          points={[
            [node.east, nodeY, node.north],
            [node.east + (contact.east - node.east) * progress.measure, nodeY + (targetY - nodeY) * progress.measure, node.north + (contact.north - node.north) * progress.measure],
          ]}
          color="#edf0e8"
          dashed
          dashSize={6}
          gapSize={4}
          lineWidth={1}
        />
      )}
      {progress.measure > 0.4 && (
        <Html position={[midE, (nodeY + targetY) / 2 + 4, midN]} center zIndexRange={[18, 0]}>
          <div
            className="font-mono"
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--hud-dim)',
              color: 'var(--hud-line)',
              fontSize: 11,
              padding: '2px 6px',
              opacity: Math.min(1, (progress.measure - 0.4) / 0.3),
              whiteSpace: 'nowrap',
            }}
          >
            {contact.shot.distance_m.toFixed(1)} m
          </div>
        </Html>
      )}

      {/* bearing arc from north reference to reported bearing */}
      {progress.bearing > 0.01 && (
        <>
          <Line points={arcPoints(node.east, node.north, nodeY + 0.2, 0, contact.shot.azimuth_deg, 45, progress.bearing)} color="#edf0e8" lineWidth={1} />
          {truth && (
            <mesh position={[node.east, nodeY + 0.1, node.north]} rotation={[-Math.PI / 2, 0, 0]}>
              <primitive object={wedgeGeometry(truth.azimuth_deg, contact.shot.azimuth_deg, 40)} attach="geometry" />
              <meshBasicMaterial color="#ffb627" transparent opacity={0.35 * progress.bearing} side={THREE.DoubleSide} depthWrite={false} />
            </mesh>
          )}
        </>
      )}
    </group>
  );
}
