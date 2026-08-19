import { useMemo } from 'react';
import * as THREE from 'three';
import { useGdsStore } from '../store';
import { EXTENT } from './Terrain';
import { buildGroundGeometry, GROUND_SEGMENTS } from './terrainGen';
import { bakeGridTexture } from '../data/grid';

const SURFACE_OFFSET = 0.4;

// Purely decorative — faint reference lines, nothing more. Deliberately has
// no pointer handlers: Terrain.tsx owns all click/hover interaction (see the
// comment there for why), so this mesh is fully transparent to raycasting —
// R3F only tests objects that register handlers, so clicks pass straight
// through it to the terrain beneath.
export default function GridOverlay() {
  const tab = useGdsStore((s) => s.tab);
  const manualMode = useGdsStore((s) => s.manualMode);

  const geometry = useMemo(() => buildGroundGeometry(EXTENT, GROUND_SEGMENTS, SURFACE_OFFSET), []);

  const texture = useMemo(() => {
    const canvas = bakeGridTexture(1024);
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }, []);

  if (!(tab === 1 && manualMode)) return null;

  return (
    <mesh geometry={geometry}>
      <meshBasicMaterial map={texture} transparent opacity={1} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  );
}
