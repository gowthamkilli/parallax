import { useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html, Line } from '@react-three/drei';
import * as THREE from 'three';
import { UNITS, NODES, PERSONNEL } from '../data/layout';
import { heightAt } from './terrainGen';
import { EXTENT } from './Terrain';

function groundY(east: number, north: number): number {
  return heightAt(east / EXTENT + 0.5, north / EXTENT + 0.5) + 0.4;
}

function ringPoints(radius: number, segments = 64): [number, number, number][] {
  const pts: [number, number, number][] = [];
  for (let i = 0; i <= segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    pts.push([Math.cos(a) * radius, 0, Math.sin(a) * radius]);
  }
  return pts;
}

function arcPoints(radius: number, spanDeg: number, segments = 20): [number, number, number][] {
  const pts: [number, number, number][] = [];
  const span = (spanDeg * Math.PI) / 180;
  for (let i = 0; i <= segments; i++) {
    const a = (i / segments) * span;
    pts.push([Math.cos(a) * radius, 0, Math.sin(a) * radius]);
  }
  return pts;
}

function rosettePoints(heading: number, radius = 14, lobes = 6): [number, number, number][] {
  const pts: [number, number, number][] = [];
  for (let i = 0; i <= lobes * 12; i++) {
    const t = (i / (lobes * 12)) * Math.PI * 2;
    const r = radius * (0.35 + 0.65 * Math.abs(Math.cos(lobes * t * 0.5)));
    const a = t + (heading * Math.PI) / 180;
    pts.push([Math.sin(a) * r, 0, Math.cos(a) * r]);
  }
  return pts;
}

function UnitHover({ unit }: { unit: (typeof UNITS)[number] }) {
  return (
    <div
      className="font-mono pointer-events-none select-none"
      style={{
        background: 'var(--panel)',
        border: '1px solid var(--hud-dim)',
        color: 'var(--hud-line)',
        padding: '8px 10px',
        fontSize: 12,
        lineHeight: 1.6,
        whiteSpace: 'pre',
        minWidth: 220,
        transform: 'translate(14px, -14px)',
      }}
    >
      <div className="label" style={{ color: 'var(--friendly)', fontSize: 15, marginBottom: 4 }}>
        {unit.callsign} <span style={{ color: 'var(--hud-dim)', fontSize: 11 }}>ACTIVE</span>
      </div>
      {`PERSONNEL      ${unit.personnelCount}
SENSOR NODES   3 / 3 ONLINE
ARRAY          6-MIC HEX / FPGA
LINK           ${unit.linkStatus}  RSSI ${unit.rssi_dbm} dBm
POWER          ${unit.power_pct}%`}
    </div>
  );
}

// Slow rotating sweep arc + a breathing rosette + a continuous ping ripple —
// makes an idle node read as "actively listening" rather than a static icon.
function NodeMarker({ node, phase }: { node: (typeof NODES)[number]; phase: number }) {
  const [hover, setHover] = useState(false);
  const y = groundY(node.east, node.north);
  const rosette = useMemo(() => rosettePoints(node.heading_deg), [node.heading_deg]);
  const rosetteLineRef = useRef<THREE.Object3D & { material: THREE.LineBasicMaterial }>(null);
  const pingRef = useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (rosetteLineRef.current) {
      const breathe = 0.14 + Math.sin(t * 1.1 + phase) * 0.06;
      rosetteLineRef.current.material.opacity = hover ? 0.85 : breathe;
    }
    if (pingRef.current) {
      const cycle = 2.6;
      const local = ((t + phase) % cycle) / cycle;
      const s = 1 + local * 7;
      pingRef.current.scale.set(s, s, s);
      (pingRef.current.material as THREE.MeshBasicMaterial).opacity = Math.max(0, 0.5 * (1 - local));
    }
  });

  return (
    <group position={[node.east, y, node.north]}>
      <mesh ref={pingRef} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[3.6, 4.2, 32]} />
        <meshBasicMaterial color="#7fe3b0" transparent opacity={0} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      <Line ref={rosetteLineRef as any} points={rosette} color="#7fe3b0" lineWidth={1} transparent opacity={0.15} />
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHover(true);
        }}
        onPointerOut={() => setHover(false)}
      >
        <ringGeometry args={[3.2, 4.6, 6]} />
        <meshBasicMaterial color="#7fe3b0" />
      </mesh>
      {hover && (
        <Html center={false} distanceFactor={0} zIndexRange={[20, 0]}>
          <div
            className="font-mono pointer-events-none select-none"
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--friendly)',
              color: 'var(--hud-line)',
              padding: '4px 8px',
              fontSize: 11,
              transform: 'translate(10px,-10px)',
            }}
          >
            {node.id} · ONLINE
          </div>
        </Html>
      )}
    </group>
  );
}

// One shared driver for all personnel dots + unit-ring sweeps, rather than a
// useFrame per element — same visual result, far fewer frame subscriptions.
function LiveMarkers() {
  const dotRefs = useRef<(THREE.Mesh | null)[]>([]);
  const sweepRefs = useRef<(THREE.Group | null)[]>([]);
  const friendlies = useMemo(() => PERSONNEL.filter((p) => !p.isNodeCarrier), []);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    dotRefs.current.forEach((m, i) => {
      if (!m) return;
      const phase = i * 0.7;
      const breathe = 0.55 + Math.sin(t * 1.6 + phase) * 0.3;
      (m.material as THREE.MeshBasicMaterial).opacity = Math.max(0.25, breathe);
      const s = 1 + Math.sin(t * 1.6 + phase) * 0.12;
      m.scale.set(s, s, s);
    });
    sweepRefs.current.forEach((g, i) => {
      if (!g) return;
      g.rotation.y = t * (0.35 + i * 0.05);
    });
  });

  return (
    <group>
      {friendlies.map((p, i) => {
        const y = groundY(p.east, p.north);
        return (
          <mesh
            key={p.id}
            ref={(el) => {
              dotRefs.current[i] = el;
            }}
            position={[p.east, y, p.north]}
            rotation={[-Math.PI / 2, 0, 0]}
          >
            <circleGeometry args={[1.3, 8]} />
            <meshBasicMaterial color="#7fe3b0" transparent opacity={0.85} />
          </mesh>
        );
      })}

      {UNITS.map((u, i) => {
        const y = groundY(u.centerEast, u.centerNorth);
        const arc = arcPoints(u.radius, 55);
        return (
          <group
            key={`sweep-${u.id}`}
            ref={(el) => {
              sweepRefs.current[i] = el;
            }}
            position={[u.centerEast, y + 0.15, u.centerNorth]}
          >
            <Line points={arc} color="#7fe3b0" lineWidth={2.2} transparent opacity={0.8} />
          </group>
        );
      })}
    </group>
  );
}

export default function UnitsLayer() {
  const [hoverUnit, setHoverUnit] = useState<string | null>(null);

  return (
    <group>
      {UNITS.map((u) => {
        const y = groundY(u.centerEast, u.centerNorth);
        const ring = ringPoints(u.radius);
        return (
          <group key={u.id} position={[u.centerEast, y, u.centerNorth]}>
            <Line
              points={ring}
              color="#7fe3b0"
              lineWidth={1.4}
              transparent
              opacity={0.4}
              onPointerOver={(e: any) => {
                e.stopPropagation();
                setHoverUnit(u.id);
              }}
              onPointerOut={() => setHoverUnit(null)}
            />
            <Line points={[[0, 0, 0], [u.radius + 60, 0, -40]]} color="#7fe3b0" opacity={0.4} transparent lineWidth={1} />
            <Html position={[u.radius + 60, 0, -40]} zIndexRange={[10, 0]}>
              <div
                className="label"
                style={{ color: 'var(--friendly)', fontSize: 15, transform: 'translateY(-50%)', whiteSpace: 'nowrap' }}
              >
                {u.callsign}
              </div>
            </Html>
            {hoverUnit === u.id && (
              <Html position={[0, 0, 0]} zIndexRange={[30, 0]}>
                <UnitHover unit={u} />
              </Html>
            )}
          </group>
        );
      })}

      <LiveMarkers />

      {NODES.map((n, i) => (
        <NodeMarker key={n.id} node={n} phase={i * 0.9} />
      ))}
    </group>
  );
}

export { groundY };
