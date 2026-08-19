import { useMemo } from 'react';
import type { ThreeEvent } from '@react-three/fiber';
import * as THREE from 'three';
import { AO } from '../geo';
import { bakeTerrainCanvas, heightAt } from './terrainGen';
import { useGdsStore } from '../store';

const EXTENT = AO.extent_m;
const SEGMENTS = 160;

export default function Terrain() {
  const geometry = useMemo(() => {
    const geo = new THREE.PlaneGeometry(EXTENT, EXTENT, SEGMENTS, SEGMENTS);
    geo.rotateX(-Math.PI / 2);
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      const u = x / EXTENT + 0.5;
      const v = z / EXTENT + 0.5;
      pos.setY(i, heightAt(u, v));
    }
    geo.computeVertexNormals();
    return geo;
  }, []);

  const texture = useMemo(() => {
    const canvas = bakeTerrainCanvas(1024);
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 4;
    return tex;
  }, []);

  const manualMode = useGdsStore((s) => s.manualMode);
  const fireManual = useGdsStore((s) => s.fireManual);
  const tab = useGdsStore((s) => s.tab);

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (!manualMode || tab !== 1) return;
    e.stopPropagation();
    fireManual(e.point.x, e.point.z);
  };

  return (
    <mesh geometry={geometry} receiveShadow onClick={handleClick}>
      <meshStandardMaterial map={texture} roughness={1} metalness={0} />
    </mesh>
  );
}

export { EXTENT };
