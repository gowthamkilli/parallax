import { Canvas } from '@react-three/fiber';
import Terrain from './Terrain';
import Trees from './Trees';
import Lighting from './Lighting';
import CameraRig from './CameraRig';
import UnitsLayer from './UnitsLayer';
import HostilesLayer from './HostilesLayer';
import WavefrontLayer from './WavefrontLayer';
import VerificationOverlay from './VerificationOverlay';
import GridOverlay from './GridOverlay';
import ResizeGuard from './ResizeGuard';

export default function Scene() {
  return (
    <Canvas shadows dpr={[1, 1.5]} gl={{ antialias: true }}>
      <color attach="background" args={['#0a0d09']} />
      <fog attach="fog" args={['#20261a', 3000, 9000]} />
      <ResizeGuard />
      <CameraRig />
      <Lighting />
      <Terrain />
      <Trees />
      <UnitsLayer />
      <HostilesLayer />
      <GridOverlay />
      <WavefrontLayer />
      <VerificationOverlay />
    </Canvas>
  );
}
