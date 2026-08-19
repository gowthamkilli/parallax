import { AO } from '../geo';

const EXTENT = AO.extent_m;

export default function Lighting() {
  // 28deg elevation directional light -> long shadows are the primary 3D cue.
  const elevRad = (28 * Math.PI) / 180;
  const dist = EXTENT * 0.9;
  const y = Math.sin(elevRad) * dist;
  const horiz = Math.cos(elevRad) * dist;

  return (
    <>
      <directionalLight
        position={[horiz * 0.6, y, horiz * 0.8]}
        intensity={2.4}
        color="#ffe9c4"
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-EXTENT / 2}
        shadow-camera-right={EXTENT / 2}
        shadow-camera-top={EXTENT / 2}
        shadow-camera-bottom={-EXTENT / 2}
        shadow-camera-near={10}
        shadow-camera-far={dist * 2}
        shadow-bias={-0.0015}
      />
      <hemisphereLight args={['#8fa6c9', '#2a2a1e', 0.55]} />
    </>
  );
}
