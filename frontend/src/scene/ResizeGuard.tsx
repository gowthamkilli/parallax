import { useEffect } from 'react';
import { useThree } from '@react-three/fiber';

// Defensive fix for a rendering bug seen when the canvas is resized at
// runtime (e.g. the window is resized after mount): the WebGL context can be
// left with a stale scissor rectangle sized for the OLD, smaller canvas,
// clipping every subsequent frame's render to that small corner even though
// the canvas element and drawing buffer report the correct new size. Forcing
// scissor test off and the scissor box back to full-canvas on every resize
// clears that stale state.
export default function ResizeGuard() {
  const gl = useThree((s) => s.gl);
  const width = useThree((s) => s.size.width);
  const height = useThree((s) => s.size.height);

  useEffect(() => {
    const ctx = gl.getContext();
    ctx.disable(ctx.SCISSOR_TEST);
    ctx.scissor(0, 0, ctx.drawingBufferWidth, ctx.drawingBufferHeight);
    ctx.viewport(0, 0, ctx.drawingBufferWidth, ctx.drawingBufferHeight);
  }, [gl, width, height]);

  return null;
}
