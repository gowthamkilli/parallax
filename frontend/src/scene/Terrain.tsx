import { useMemo, useState } from 'react';
import type { ThreeEvent } from '@react-three/fiber';
import * as THREE from 'three';
import { AO } from '../geo';
import { bakeTerrainCanvas, buildGroundGeometry, GROUND_SEGMENTS, heightAt } from './terrainGen';
import { useGdsStore } from '../store';
import { cellAt, type GridCell } from '../data/grid';

const EXTENT = AO.extent_m;

export default function Terrain() {
  const geometry = useMemo(() => buildGroundGeometry(EXTENT, GROUND_SEGMENTS), []);

  const texture = useMemo(() => {
    const canvas = bakeTerrainCanvas(1024);
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 4;
    return tex;
  }, []);

  const tab = useGdsStore((s) => s.tab);
  const manualMode = useGdsStore((s) => s.manualMode);
  const manualPending = useGdsStore((s) => s.manualPending);
  const fireManualAtCell = useGdsStore((s) => s.fireManualAtCell);
  const [hovered, setHovered] = useState<GridCell | null>(null);

  // Click/hover handling lives on THIS mesh — the exact one being rendered —
  // rather than a separate overlay mesh. A separate overlay built with even
  // slightly different vertex density interpolates the same height function
  // differently between vertices, so a raycast against it lands at a
  // different (x,z) than what's visually under the cursor. Raycasting the
  // rendered surface itself makes that class of bug impossible.
  const active = tab === 1 && manualMode;

  const handleMove = (e: ThreeEvent<PointerEvent>) => {
    if (!active) return;
    e.stopPropagation();
    setHovered(cellAt(e.point.x, e.point.z));
  };

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (!active || manualPending) return;
    e.stopPropagation();
    const cell = cellAt(e.point.x, e.point.z);
    if (cell) fireManualAtCell(cell);
  };

  return (
    <group>
      <mesh
        geometry={geometry}
        receiveShadow
        onPointerMove={active ? handleMove : undefined}
        onPointerOut={active ? () => setHovered(null) : undefined}
        onClick={active ? handleClick : undefined}
      >
        <meshStandardMaterial map={texture} roughness={1} metalness={0} />
      </mesh>

      {/* hover indicator — where a click will land, no numbers, just a mark */}
      {active && hovered && (
        <mesh
          position={[hovered.east, heightAt(hovered.east / EXTENT + 0.5, hovered.north / EXTENT + 0.5) + 0.8, hovered.north]}
          rotation={[-Math.PI / 2, 0, 0]}
        >
          <ringGeometry args={[6, 8, 32]} />
          <meshBasicMaterial color="#7fe3b0" transparent opacity={0.7} side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      )}
    </group>
  );
}

export { EXTENT };
