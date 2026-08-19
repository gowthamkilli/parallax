import { useMemo, useState } from 'react';
import { Html, Line } from '@react-three/drei';
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

function NodeMarker({ node }: { node: (typeof NODES)[number] }) {
  const [hover, setHover] = useState(false);
  const y = groundY(node.east, node.north);
  const rosette = useMemo(() => rosettePoints(node.heading_deg), [node.heading_deg]);

  return (
    <group position={[node.east, y, node.north]}>
      <Line points={rosette} color="#7fe3b0" lineWidth={1} transparent opacity={hover ? 0.85 : 0.15} />
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
              opacity={0.55}
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

      {PERSONNEL.filter((p) => !p.isNodeCarrier).map((p) => {
        const y = groundY(p.east, p.north);
        return (
          <mesh key={p.id} position={[p.east, y, p.north]} rotation={[-Math.PI / 2, 0, 0]}>
            <circleGeometry args={[1.3, 8]} />
            <meshBasicMaterial color="#7fe3b0" transparent opacity={0.85} />
          </mesh>
        );
      })}

      {NODES.map((n) => (
        <NodeMarker key={n.id} node={n} />
      ))}
    </group>
  );
}

export { groundY };
