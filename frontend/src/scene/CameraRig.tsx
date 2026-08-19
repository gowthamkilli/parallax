import { useEffect, useRef } from 'react';
import { PerspectiveCamera } from '@react-three/drei';
import { useThree } from '@react-three/fiber';
import gsap from 'gsap';
import * as THREE from 'three';
import { useGdsStore } from '../store';
import { nodeById } from '../data/layout';

const FOV = 22;
const TILT_DEG = 16;

function framingFor(
  tab: 1 | 2 | 3,
  focusEast: number,
  focusNorth: number
): { altitude: number; east: number; north: number } {
  if (tab === 3) return { altitude: 5200, east: 0, north: -80 };
  if (tab === 2) return { altitude: 2400, east: focusEast * 0.5, north: focusNorth * 0.5 };
  return { altitude: 3600, east: 0, north: 0 };
}

function destFor(tab: 1 | 2 | 3, focusEast: number, focusNorth: number) {
  const { altitude, east, north } = framingFor(tab, focusEast, focusNorth);
  const tiltOffset = altitude * Math.tan((TILT_DEG * Math.PI) / 180);
  return { x: east, y: altitude, z: north + tiltOffset, tx: east, ty: 0, tz: north };
}

// Tab 1's default framing, computed once — used for both the JSX camera's
// initial position and the GSAP proxy's starting values so the very first
// paint is already correctly aimed, with no dependency on a tween tick ever
// firing (see the mountedRef branch below: gsap.set applies synchronously,
// gsap.to does not run until the next animation frame).
const INITIAL = destFor(1, 0, 0);

export default function CameraRig() {
  const { camera } = useThree();
  const tab = useGdsStore((s) => s.tab);
  const activeShot = useGdsStore((s) => s.activeShot);
  const reducedMotion = useGdsStore((s) => s.reducedMotion);
  const targetRef = useRef(new THREE.Vector3(INITIAL.tx, INITIAL.ty, INITIAL.tz));
  const proxy = useRef({ ...INITIAL });
  const mountedRef = useRef(false);

  useEffect(() => {
    const node = activeShot ? nodeById(activeShot.shot.detecting_node) : undefined;
    const focusEast = node?.east ?? 0;
    const focusNorth = node?.north ?? 0;
    const dest = destFor(tab, focusEast, focusNorth);

    const applyToCamera = () => {
      camera.position.set(proxy.current.x, proxy.current.y, proxy.current.z);
      targetRef.current.set(proxy.current.tx, proxy.current.ty, proxy.current.tz);
      camera.lookAt(targetRef.current);
    };

    if (!mountedRef.current) {
      // First mount: apply instantly via gsap.set, which mutates and fires
      // synchronously rather than waiting on the rAF-driven ticker.
      mountedRef.current = true;
      gsap.set(proxy.current, dest);
      applyToCamera();
      return;
    }

    gsap.to(proxy.current, {
      ...dest,
      duration: reducedMotion ? 0 : 0.7,
      ease: 'power2.inOut',
      onUpdate: applyToCamera,
    });
  }, [tab, activeShot?.runId, camera, reducedMotion]);

  return (
    <PerspectiveCamera
      makeDefault
      fov={FOV}
      near={10}
      far={20000}
      position={[INITIAL.x, INITIAL.y, INITIAL.z]}
    />
  );
}
