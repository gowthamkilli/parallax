import { Canvas } from '@react-three/fiber';
import Terrain from './Terrain';
import Trees from './Trees';
import Lighting from './Lighting';
import CameraRig from './CameraRig';
import UnitsLayer from './UnitsLayer';
import HostilesLayer from './HostilesLayer';
import WavefrontLayer from './WavefrontLayer';
import VerificationOverlay from './VerificationOverlay';

export default function Scene() {
  return (
    <Canvas shadows dpr={[1, 1.5]} gl={{ antialias: true }}>
      <color attach="background" args={['#0a0d09']} />
      <fog attach="fog" args={['#20261a', 3000, 9000]} />
      <CameraRig />
      <Lighting />
      <Terrain />
      <Trees />
      <UnitsLayer />
      <HostilesLayer />
      <WavefrontLayer />
      <VerificationOverlay />
    </Canvas>
  );
}
