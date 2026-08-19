import { useLayoutEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { classify, heightAt } from './terrainGen';
import { EXTENT } from './Terrain';

const TARGET_COUNT = 9000;
const GRID = 150;

function hash01(i: number, seed: number): number {
  let h = i * 2654435761 + seed * 40503;
  h = (h ^ (h >>> 13)) * 1274126177;
  h = h ^ (h >>> 16);
  return ((h >>> 0) % 100000) / 100000;
}

interface TreeInstance {
  x: number;
  y: number;
  z: number;
  scale: number;
  rot: number;
}

function buildInstances(): TreeInstance[] {
  const candidates: TreeInstance[] = [];
  const cell = EXTENT / GRID;
  let seed = 101;
  for (let gx = 0; gx < GRID; gx++) {
    for (let gz = 0; gz < GRID; gz++) {
      seed++;
      const jx = (hash01(seed, 1) - 0.5) * cell;
      const jz = (hash01(seed, 2) - 0.5) * cell;
      const x = (gx / GRID - 0.5) * EXTENT + cell / 2 + jx;
      const z = (gz / GRID - 0.5) * EXTENT + cell / 2 + jz;
      const u = x / EXTENT + 0.5;
      const v = z / EXTENT + 0.5;
      const { cover, canopyMask } = classify(u, v);
      if (cover !== 'canopy') continue;
      // feather density at canopy edges rather than a hard cutoff
      const density = 0.25 + canopyMask * 0.75;
      if (hash01(seed, 3) > density) continue;
      const y = heightAt(u, v);
      const scale = 0.7 + hash01(seed, 4) * 0.9;
      const rot = hash01(seed, 5) * Math.PI * 2;
      candidates.push({ x, y, z, scale, rot });
    }
  }
  // Cap to target budget, sampling evenly rather than truncating one region.
  if (candidates.length <= TARGET_COUNT) return candidates;
  const stride = candidates.length / TARGET_COUNT;
  const out: TreeInstance[] = [];
  for (let i = 0; i < TARGET_COUNT; i++) out.push(candidates[Math.floor(i * stride)]);
  return out;
}

export default function Trees() {
  const instances = useMemo(buildInstances, []);
  const trunkRef = useRef<THREE.InstancedMesh>(null);
  const canopyRef = useRef<THREE.InstancedMesh>(null);

  useLayoutEffect(() => {
    const dummy = new THREE.Object3D();
    instances.forEach((t, i) => {
      dummy.position.set(t.x, t.y + 1.6 * t.scale, t.z);
      dummy.rotation.set(0, t.rot, 0);
      dummy.scale.set(t.scale, t.scale, t.scale);
      dummy.updateMatrix();
      trunkRef.current?.setMatrixAt(i, dummy.matrix);

      dummy.position.set(t.x, t.y + 4.2 * t.scale, t.z);
      dummy.updateMatrix();
      canopyRef.current?.setMatrixAt(i, dummy.matrix);
    });
    if (trunkRef.current) trunkRef.current.instanceMatrix.needsUpdate = true;
    if (canopyRef.current) canopyRef.current.instanceMatrix.needsUpdate = true;
  }, [instances]);

  const trunkGeo = useMemo(() => new THREE.CylinderGeometry(0.25, 0.35, 3.2, 5), []);
  const canopyGeo = useMemo(() => new THREE.ConeGeometry(2.4, 6, 6), []);

  return (
    <group>
      <instancedMesh ref={trunkRef} args={[trunkGeo, undefined, instances.length]} castShadow>
        <meshStandardMaterial color="#3a2f1f" roughness={1} />
      </instancedMesh>
      <instancedMesh ref={canopyRef} args={[canopyGeo, undefined, instances.length]} castShadow>
        <meshStandardMaterial color="#28381d" roughness={0.95} />
      </instancedMesh>
    </group>
  );
}
