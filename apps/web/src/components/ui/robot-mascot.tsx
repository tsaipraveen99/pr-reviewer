// Brand-adapted composition of the robot: our canvas, our colors, no
// marketplace navbar. Loaded lazily from the landing so the three.js stack
// stays out of the main bundle.

import { Canvas } from "@react-three/fiber";
import { ContactShadows, Environment } from "@react-three/drei";
import { ResponsiveGroup, RobotPrototype } from "@/components/ui/robot-hero";

export default function RobotMascot() {
  return (
    <Canvas
      shadows
      camera={{ position: [0, 0.2, 6], fov: 40 }}
      gl={{ alpha: true, antialias: true }}
      style={{ background: "transparent" }}
    >
      <ambientLight intensity={0.85} color="#ffffff" />
      <Environment preset="studio" blur={0.5} />
      <ResponsiveGroup scale={1}>
        <ContactShadows
          position={[0, -0.79, 0]}
          opacity={0.55}
          scale={15}
          resolution={1024}
          blur={1.7}
          far={2.5}
          color="#000000"
        />
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
