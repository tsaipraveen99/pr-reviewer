// Brand-adapted composition of the robot: our canvas, our colors, no
// marketplace navbar. Deliberately LIGHTWEIGHT: no shadow maps, no
// ContactShadows render pass, no external HDR environment, capped DPR --
// heavyweight contexts are exactly what Chrome's GPU process kills on
// busy machines (white canvas + sad-tab icon). Ground shadow is CSS.
// A lost context recreates the Canvas up to twice, then degrades politely.

import { useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { ResponsiveGroup, RobotPrototype } from "@/components/ui/robot-hero";

export default function RobotMascot() {
  const [generation, setGeneration] = useState(0);
  const [dead, setDead] = useState(false);
  const attempts = useRef(0);

  if (dead) {
    return (
      <div className="mascot-loading mono">
        your GPU declined to render the robot — it sends its regards
      </div>
    );
  }

  return (
    <Canvas
      key={generation}
      camera={{ position: [0, 0.2, 6], fov: 40 }}
      dpr={[1, 1.5]}
      gl={{ alpha: true, antialias: true, powerPreference: "low-power" }}
      style={{ background: "transparent" }}
      onCreated={({ gl }) => {
        gl.domElement.addEventListener("webglcontextlost", (e) => {
          e.preventDefault();
          attempts.current += 1;
          if (attempts.current > 2) {
            setDead(true);
          } else {
            setTimeout(() => setGeneration((g) => g + 1), 800);
          }
        });
      }}
    >
      <ambientLight intensity={1.25} color="#ffffff" />
      <directionalLight position={[2, 4, 3]} intensity={0.9} color="#ffffff" />
      <directionalLight position={[-3, 2, -2]} intensity={0.25} color="#dfe8e2" />
      <ResponsiveGroup scale={1}>
        <RobotPrototype
          neckParams={{
            baseR: 0.215,
            baseH: -0.05,
            midR: 0.28,
            midH: 0.02,
            lipBottomR: 0.295,
            lipBottomH: 0.045,
            lipTopR: 0.27,
            lipTopH: 0.055,
            innerR: 0.1,
            innerDropH: 0.0,
          }}
          bodyParams={{ bodyBevelR: 0.235, bodyBevelY: 0.34, bodyBevelT: 0.025 }}
          color="#c4c4c4"
          pantallaColor="#46c28e"
          pantallaBrillo={1.25}
          blinkCycle={3.0}
          metalness={0.0}
        />
      </ResponsiveGroup>
    </Canvas>
  );
}
